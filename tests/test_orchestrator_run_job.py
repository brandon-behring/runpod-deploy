"""End-to-end orchestrator tests; mock provider+transport subprocess calls in one go."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from runpod_deploy import orchestrator, provider
from runpod_deploy.config import load_job_spec
from runpod_deploy.orchestrator import run_job
from runpod_deploy.transport import RemoteRunner
from tests.conftest import FakeResult, FakeSubprocess


@pytest.fixture(autouse=True)
def _stub_supported_flags_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the `runpodctl pod create --help` probe.

    Without this stub, ``provider._supported_pod_create_flags`` shells
    out once per Python process to detect the locally-installed
    runpodctl's flag set, consuming an unrelated FakeResult from the
    FIFO queue and breaking the per-test argv assertions. Mirrors the
    autouse fixture in tests/test_provider_subprocess.py.
    """
    monkeypatch.setattr(provider, "_supported_pod_create_flags", lambda: frozenset())


def _write_full_config(
    tmp_path: Path,
    *,
    storage_mode: str = "network_volume",
    cost_cap_usd: float = 50.0,
    hourly_rate_usd: float = 2.0,
    max_runtime_minutes: int = 30,
    poll_interval_sec: int = 5,
    on_success: str = "delete",
    on_failure: str = "stop",
    ssh_ready_timeout_sec: int | None = None,
    artifact_required: bool = True,
    with_env: bool = False,
) -> Path:
    state_file = tmp_path / "state.json"
    ssh_key = tmp_path / "id_ed25519"
    ssh_key.write_text("dummy")
    project = tmp_path / "project"
    project.mkdir()
    (project / "marker.txt").write_text("data")
    pull_dir = tmp_path / "pulled"

    if storage_mode == "network_volume":
        storage_block = (
            "storage:\n"
            "  mode: network_volume\n"
            "  volume_name: my-vol\n"
            "  volume_mount: /workspace\n"
        )
    else:
        storage_block = "storage:\n  mode: ephemeral\n  volume_gb: 20\n"

    budget_block = (
        f"budget:\n"
        f"  cost_cap_usd: {cost_cap_usd}\n"
        f"  assumed_hourly_rate_usd: {hourly_rate_usd}\n"
        f"  max_runtime_minutes: {max_runtime_minutes}\n"
        f"  poll_interval_sec: {poll_interval_sec}\n"
    )
    if ssh_ready_timeout_sec is not None:
        budget_block += f"  ssh_ready_timeout_sec: {ssh_ready_timeout_sec}\n"

    env_block = ""
    if with_env:
        env_block = (
            "remote_env:\n"
            "  exports:\n"
            "    FOO: bar\n"
            "  source_files:\n"
            "    - /etc/profile.d/runpod.sh\n"
            "setup:\n"
            "  - command: echo hello\n"
            "    with_env: true\n"
        )

    config = tmp_path / "job.yaml"
    config.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
state_file: {state_file}
local:
  project_root: {project}
ssh:
  key_path: {ssh_key}
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenters: [US-MD-1]
  gpu_order:
    - NVIDIA A100-SXM4-80GB
{storage_block}{budget_block}run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
{env_block}staging:
  - label: repo
    source: "{{project_root}}/"
    destination: "/workspace/demo/"
    delete: false
artifacts:
  - label: log
    remote_path: /workspace/demo.log
    local_path: "{pull_dir}"
    required: {str(artifact_required).lower()}
    delete: false
lifecycle:
  on_success: {on_success}
  on_failure: {on_failure}
""")
    return config


def _enqueue_runpodctl_happy_path(fake: FakeSubprocess) -> None:
    # Predicate-routed responses for telemetry/metadata side-channel calls so the
    # FIFO queue below stays focused on the four primary provisioning calls.
    fake.when(
        lambda argv: bool(argv) and argv[0] == "git",
        FakeResult(returncode=128, stderr="fatal: not a git repository"),
    )
    fake.when(
        lambda argv: bool(argv)
        and argv[:3] == ["runpodctl", "pod", "get"]
        and "--include-machine" in argv,
        FakeResult(
            stdout=json.dumps({"id": "pod-xyz", "costPerHr": 0.35, "desiredStatus": "RUNNING"})
        ),
    )
    fake.when(
        lambda argv: bool(argv) and argv[:3] == ["runpodctl", "pod", "stop"],
        FakeResult(returncode=0),
    )
    fake.when(
        lambda argv: bool(argv) and argv[:3] == ["runpodctl", "pod", "delete"],
        FakeResult(returncode=0),
    )
    # FIFO order matches orchestrator: datacenter list (GPU selection) → network-volume
    # list (volume resolution against selected DC) → pod create → pod get (ready).
    fake.enqueue(
        FakeResult(
            stdout=json.dumps(
                [
                    {
                        "id": "US-MD-1",
                        "gpuAvailability": [
                            {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": "High"}
                        ],
                    }
                ]
            )
        ),
        FakeResult(
            stdout=json.dumps([{"id": "vol-1", "name": "my-vol", "dataCenterId": "US-MD-1"}])
        ),
        FakeResult(stdout=json.dumps({"id": "pod-xyz"})),
        FakeResult(
            stdout=json.dumps({"desiredStatus": "RUNNING", "ssh": {"ip": "5.6.7.8", "port": 22033}})
        ),
    )


def _is_monitor_tail(argv: list[str]) -> bool:
    return bool(argv) and argv[0] == "ssh" and "tail -n 80" in argv[-1]


def _freeze_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("runpod_deploy.orchestrator.time.time", lambda: 1000.0)
    monkeypatch.setattr("runpod_deploy.orchestrator.time.sleep", lambda _s: None)
    monkeypatch.setattr("runpod_deploy.provider.time.time", lambda: 1000.0)
    monkeypatch.setattr("runpod_deploy.provider.time.sleep", lambda _s: None)


# ---------- happy path ----------


@pytest.mark.unit
def test_run_job_full_happy_path_network_volume(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(
        _is_monitor_tail, FakeResult(stdout="tail output\n__RUNPOD_DEPLOY_DONE__\n")
    )
    config = _write_full_config(tmp_path)
    spec = load_job_spec(config)

    run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    argv_strs = [" ".join(c) for c in fake_subprocess.calls]
    assert any("runpodctl network-volume list" in s for s in argv_strs)
    assert any("runpodctl datacenter list" in s for s in argv_strs)
    assert any("runpodctl pod create" in s for s in argv_strs)
    assert any("runpodctl pod get pod-xyz" in s for s in argv_strs)
    assert any(s.startswith("rsync ") for s in argv_strs)
    # Default lifecycle.on_success is "delete" — releases volume disk.
    assert any("runpodctl pod delete pod-xyz" in s for s in argv_strs)
    assert "__RUNPOD_DEPLOY_DONE__" in caplog.text
    # Pull manifest written under project_root/artifacts/runpod/<ts>/
    manifests = list(tmp_path.rglob("runpod_deploy_pull_manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["pod_id"] == "pod-xyz"
    assert manifest["failed"] is False


@pytest.mark.unit
def test_run_job_with_env_prefixes_setup_command(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="__RUNPOD_DEPLOY_DONE__\n"))
    config = _write_full_config(tmp_path, with_env=True)
    spec = load_job_spec(config)

    run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    setup_ssh = [c for c in fake_subprocess.calls if c and c[0] == "ssh" and "echo hello" in c[-1]]
    assert len(setup_ssh) == 1
    assert "export FOO=bar" in setup_ssh[0][-1]
    assert "/etc/profile.d/runpod.sh" in setup_ssh[0][-1]


# ---------- failure paths ----------


@pytest.mark.unit
def test_run_job_optional_artifact_pull_failure_is_warned(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="__RUNPOD_DEPLOY_DONE__\n"))
    fake_subprocess.when(
        lambda argv: (
            bool(argv) and argv[0] == "rsync" and len(argv) >= 2 and argv[-2].startswith("root@")
        ),
        FakeResult(returncode=23, stderr="rsync error"),
    )
    config = _write_full_config(tmp_path, artifact_required=False)
    spec = load_job_spec(config)

    run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    assert "[warn] optional pull skipped" in caplog.text


@pytest.mark.unit
def test_run_job_failure_marker_preserves_pod_when_on_failure_preserve(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="oops\n__RUNPOD_DEPLOY_FAIL__\n"))
    config = _write_full_config(tmp_path, on_failure="preserve")
    spec = load_job_spec(config)

    with pytest.raises(RuntimeError, match="failure marker"):
        run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    assert "preserved" in caplog.text
    stop_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "stop"]]
    delete_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "delete"]]
    assert stop_calls == []
    assert delete_calls == []


@pytest.mark.unit
def test_run_job_success_deletes_pod_by_default(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Lock the operational fix at the orchestrator level.

    On the happy path, the orchestrator MUST issue
    ``runpodctl pod delete`` (release volume storage) — and MUST NOT
    issue ``runpodctl pod stop`` (the legacy behavior that leaked).
    """
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(
        _is_monitor_tail, FakeResult(stdout="tail output\n__RUNPOD_DEPLOY_DONE__\n")
    )
    config = _write_full_config(tmp_path)  # defaults: on_success=delete
    spec = load_job_spec(config)

    run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    delete_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "delete"]]
    stop_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "stop"]]
    assert delete_calls == [["runpodctl", "pod", "delete", "pod-xyz"]]
    assert stop_calls == []


@pytest.mark.unit
def test_run_job_failure_stops_pod_by_default_with_actionable_warning(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Lock the forensics default + the actionable WARNING contract.

    On failure with default ``on_failure=stop``, the orchestrator MUST:
    1. issue ``runpodctl pod stop`` (preserve for SSH forensics),
    2. emit a WARNING containing the literal
       ``runpod-deploy cleanup --state-file`` command and ``ls-stale``
       so the operator knows how to release the preserved pod.
    """
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="oops\n__RUNPOD_DEPLOY_FAIL__\n"))
    config = _write_full_config(tmp_path)  # defaults: on_failure=stop
    spec = load_job_spec(config)

    with pytest.raises(RuntimeError, match="failure marker"):
        run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    stop_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "stop"]]
    delete_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "delete"]]
    assert stop_calls == [["runpodctl", "pod", "stop", "pod-xyz"]]
    assert delete_calls == []
    # Operator nudge — load-bearing for preventing the 2026-05-17 leak recurrence.
    assert "runpod-deploy cleanup --state-file" in caplog.text
    assert "ls-stale" in caplog.text


@pytest.mark.unit
def test_run_job_budget_cap_exceeded_raises_before_provisioning(
    tmp_path: Path,
) -> None:
    # rate=2/hr * runtime=2h = $4 > cap $1
    config = _write_full_config(
        tmp_path,
        cost_cap_usd=1.0,
        hourly_rate_usd=2.0,
        max_runtime_minutes=120,
    )
    spec = load_job_spec(config)

    with pytest.raises(RuntimeError, match="timeout exceeds cost cap"):
        run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)


@pytest.mark.unit
def test_preflight_failure_skips_artifact_pulls(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)

    def raise_on_setup(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated preflight failure")

    monkeypatch.setattr("runpod_deploy.orchestrator._run_commands", raise_on_setup)
    config = _write_full_config(tmp_path)
    spec = load_job_spec(config)

    with pytest.raises(RuntimeError, match="simulated preflight failure"):
        run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    rsync_calls = [c for c in fake_subprocess.calls if c and c[0] == "rsync"]
    assert rsync_calls == []
    assert "skipping artifact pulls — run script did not execute" in caplog.text


@pytest.mark.unit
def test_run_started_failure_still_attempts_pull(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="oops\n__RUNPOD_DEPLOY_FAIL__\n"))
    config = _write_full_config(tmp_path, artifact_required=False)
    spec = load_job_spec(config)

    with pytest.raises(RuntimeError, match="failure marker"):
        run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    assert "skipping artifact pulls" not in caplog.text
    pull_calls = [
        c
        for c in fake_subprocess.calls
        if c and c[0] == "rsync" and len(c) >= 2 and c[-2].startswith("root@")
    ]
    assert len(pull_calls) >= 1


# ---------- _wait_for_sshd unit ----------


@pytest.mark.unit
def test_wait_for_sshd_retries_then_raises_runtime_error(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("runpod_deploy.orchestrator.time.sleep", lambda _s: None)
    fake_subprocess.when(
        lambda argv: bool(argv) and argv[0] == "ssh" and argv[-1] == "true",
        FakeResult(returncode=255, stderr="connection refused"),
    )
    runner = RemoteRunner(
        host="1.2.3.4", port=22022, ssh_key=tmp_path / "id_ed25519", dry_run=False
    )

    with pytest.raises(RuntimeError, match="sshd never became ready"):
        orchestrator._wait_for_sshd(runner)

    ssh_calls = [c for c in fake_subprocess.calls if c[0] == "ssh"]
    assert len(ssh_calls) == 7


# ---------- budget.ssh_ready_timeout_sec plumbing (Issue #88) ----------


@pytest.mark.unit
def test_run_job_passes_default_ssh_ready_timeout_to_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default spec value (900 s) flows through run_job to provision_pod."""
    captured: dict[str, Any] = {}

    def fake_provision_pod(*args: Any, **kwargs: Any) -> provider.PodConnection:
        captured.update(kwargs)
        return provider.PodConnection(
            pod_id="<pod-id>", host="203.0.113.10", port=22022, gpu_id=kwargs["gpu_id"]
        )

    monkeypatch.setattr("runpod_deploy.orchestrator.provision_pod", fake_provision_pod)
    config = _write_full_config(tmp_path)
    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)

    assert captured["ssh_ready_timeout_sec"] == 900


@pytest.mark.unit
def test_run_job_passes_spec_ssh_ready_timeout_to_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit YAML value overrides the default."""
    captured: dict[str, Any] = {}

    def fake_provision_pod(*args: Any, **kwargs: Any) -> provider.PodConnection:
        captured.update(kwargs)
        return provider.PodConnection(
            pod_id="<pod-id>", host="203.0.113.10", port=22022, gpu_id=kwargs["gpu_id"]
        )

    monkeypatch.setattr("runpod_deploy.orchestrator.provision_pod", fake_provision_pod)
    config = _write_full_config(tmp_path, ssh_ready_timeout_sec=1200)
    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)

    assert captured["ssh_ready_timeout_sec"] == 1200


@pytest.mark.unit
def test_run_job_cli_override_wins_over_spec_ssh_ready_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLI ``ssh_ready_timeout_sec_override`` beats the spec value."""
    captured: dict[str, Any] = {}

    def fake_provision_pod(*args: Any, **kwargs: Any) -> provider.PodConnection:
        captured.update(kwargs)
        return provider.PodConnection(
            pod_id="<pod-id>", host="203.0.113.10", port=22022, gpu_id=kwargs["gpu_id"]
        )

    monkeypatch.setattr("runpod_deploy.orchestrator.provision_pod", fake_provision_pod)
    config = _write_full_config(tmp_path, ssh_ready_timeout_sec=1200)
    run_job(
        load_job_spec(config),
        config_path=config,
        offline_dry_run=True,
        ssh_ready_timeout_sec_override=300,
    )

    assert captured["ssh_ready_timeout_sec"] == 300


# ---------- lifecycle.on_success: recycle plumbing (Issue #90) ----------


@pytest.mark.unit
def test_run_job_recycle_resumes_when_state_file_points_to_compatible_pod(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When on_success: recycle and a compatible paused pod exists, resume.

    The orchestrator MUST NOT issue ``runpodctl pod create``; instead it
    must issue ``runpodctl pod start <id>`` for the pod referenced by
    the state-file.
    """
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    # Pre-write a state-file matching the spec defaults from _write_full_config.
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "pod_id": "pod-recycle",
                "gpu_id": "NVIDIA A100-SXM4-80GB",
                "image": "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
                "datacenter_id": "US-MD-1",
            }
        )
    )
    # Predicate-routed responses for try_resume_pod + happy path.
    fake_subprocess.when(
        lambda argv: bool(argv) and argv[0] == "git",
        FakeResult(returncode=128, stderr="fatal: not a git repository"),
    )
    fake_subprocess.when(
        lambda argv: bool(argv)
        and argv[:3] == ["runpodctl", "pod", "get"]
        and "--include-machine" in argv,
        FakeResult(
            stdout=json.dumps({"id": "pod-recycle", "costPerHr": 0.35, "desiredStatus": "RUNNING"})
        ),
    )
    fake_subprocess.when(
        lambda argv: bool(argv) and argv[:3] == ["runpodctl", "pod", "stop"],
        FakeResult(returncode=0),
    )
    fake_subprocess.when(
        lambda argv: bool(argv) and argv[:3] == ["runpodctl", "pod", "delete"],
        FakeResult(returncode=0),
    )
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="ok\n__RUNPOD_DEPLOY_DONE__\n"))
    # FIFO order: datacenter list (GPU/DC selection runs first), then
    # try_resume_pod's pod get (EXITED), pod start, post-start pod get (RUNNING+ssh).
    # We skip _resolve_volume_id (ephemeral storage) AND skip pod create on the
    # resume path.
    fake_subprocess.enqueue(
        FakeResult(
            stdout=json.dumps(
                [
                    {
                        "id": "US-MD-1",
                        "gpuAvailability": [
                            {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": "High"}
                        ],
                    }
                ]
            )
        ),
        FakeResult(stdout=json.dumps({"desiredStatus": "EXITED", "ssh": {}})),
        FakeResult(returncode=0),  # pod start
        FakeResult(
            stdout=json.dumps({"desiredStatus": "RUNNING", "ssh": {"ip": "5.6.7.8", "port": 22033}})
        ),
    )
    # Build the config — note: must use the SAME state_file path so the
    # orchestrator picks up our pre-written pointer.
    config = _write_full_config(
        tmp_path,
        on_success="recycle",
        storage_mode="ephemeral",  # network_volume would also trigger volume resolution
    )
    # Override state_file path in the YAML (since _write_full_config sets its own)
    config_text = config.read_text()
    config_text = re.sub(
        r"state_file: .*",
        f"state_file: {state_file}",
        config_text,
    )
    config.write_text(config_text)
    spec = load_job_spec(config)

    run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    argv_strs = [" ".join(c) for c in fake_subprocess.calls]
    assert not any(
        "runpodctl pod create" in s for s in argv_strs
    ), "must NOT pod-create when resuming"
    assert any("runpodctl pod start pod-recycle" in s for s in argv_strs), "MUST issue pod start"


@pytest.mark.unit
def test_run_job_force_fresh_skips_resume_and_deletes_stale(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """--force-fresh: skip resume even if state-file present; delete stale."""
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "pod_id": "pod-stale",
                "gpu_id": "NVIDIA A100-SXM4-80GB",
                "image": "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
                "datacenter_id": "US-MD-1",
            }
        )
    )
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="ok\n__RUNPOD_DEPLOY_DONE__\n"))
    config = _write_full_config(tmp_path, on_success="recycle")
    config_text = config.read_text()
    config_text = re.sub(r"state_file: .*", f"state_file: {state_file}", config_text)
    config.write_text(config_text)
    spec = load_job_spec(config)

    run_job(spec, config_path=config, dry_run=False, offline_dry_run=False, force_fresh=True)

    argv_strs = [" ".join(c) for c in fake_subprocess.calls]
    # Stale pod was deleted by _force_fresh_delete_stale:
    assert any("runpodctl pod delete pod-stale" in s for s in argv_strs)
    # Fresh pod was created:
    assert any("runpodctl pod create" in s for s in argv_strs)
    # No pod start (no resume attempt):
    start_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "start"]]
    assert start_calls == []


# ---------- --fallback-cloud-type ----------


@pytest.fixture
def _stub_pod_create_help_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the `runpodctl pod create --help` probe for fallback tests.

    Without this, the probe consumes the first FIFO FakeResult on cold-cache
    runs (the cache is a module-level attribute that survives across tests
    in the same pytest session). Mirrors the per-file autouse stub at
    tests/test_provider_subprocess.py:21.
    """
    from runpod_deploy import provider

    monkeypatch.setattr(provider, "_supported_pod_create_flags", lambda: frozenset())


def _enqueue_runpodctl_happy_path_ephemeral(fake: FakeSubprocess) -> None:
    """Variant of `_enqueue_runpodctl_happy_path` for storage.mode=ephemeral.

    Differs from the network-volume variant by skipping the
    `runpodctl network-volume list` call between datacenter selection
    and pod creation.
    """
    fake.when(
        lambda argv: bool(argv) and argv[0] == "git",
        FakeResult(returncode=128, stderr="fatal: not a git repository"),
    )
    fake.when(
        lambda argv: bool(argv)
        and argv[:3] == ["runpodctl", "pod", "get"]
        and "--include-machine" in argv,
        FakeResult(
            stdout=json.dumps({"id": "pod-xyz", "costPerHr": 0.35, "desiredStatus": "RUNNING"})
        ),
    )
    fake.when(
        lambda argv: bool(argv) and argv[:3] == ["runpodctl", "pod", "stop"],
        FakeResult(returncode=0),
    )
    fake.enqueue(
        FakeResult(
            stdout=json.dumps(
                [
                    {
                        "id": "US-MD-1",
                        "gpuAvailability": [
                            {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": "High"}
                        ],
                    }
                ]
            )
        ),
        FakeResult(stdout=json.dumps({"id": "pod-xyz"})),
        FakeResult(
            stdout=json.dumps({"desiredStatus": "RUNNING", "ssh": {"ip": "5.6.7.8", "port": 22033}})
        ),
    )


def _enqueue_runpodctl_fallback_path(fake: FakeSubprocess) -> None:
    """Enqueue an ephemeral-storage provisioning sequence with stock-out on first pod create."""
    # Side-channel calls (git, pod-get-machine, pod stop) — predicate-routed.
    fake.when(
        lambda argv: bool(argv) and argv[0] == "git",
        FakeResult(returncode=128, stderr="fatal: not a git repository"),
    )
    fake.when(
        lambda argv: bool(argv)
        and argv[:3] == ["runpodctl", "pod", "get"]
        and "--include-machine" in argv,
        FakeResult(
            stdout=json.dumps({"id": "pod-xyz", "costPerHr": 0.35, "desiredStatus": "RUNNING"})
        ),
    )
    fake.when(
        lambda argv: bool(argv) and argv[:3] == ["runpodctl", "pod", "stop"],
        FakeResult(returncode=0),
    )
    # FIFO: datacenter list → pod create #1 (stock-out) → pod create #2 (success) → pod get.
    # Ephemeral storage skips the network-volume list call.
    fake.enqueue(
        FakeResult(
            stdout=json.dumps(
                [
                    {
                        "id": "US-MD-1",
                        "gpuAvailability": [
                            {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": "High"}
                        ],
                    }
                ]
            )
        ),
        # Primary attempt: stock-out
        FakeResult(
            returncode=1,
            stdout='{"error":"failed to create pod: This machine does not have the resources"}',
            stderr="",
        ),
        # Fallback attempt: succeeds
        FakeResult(stdout=json.dumps({"id": "pod-xyz"})),
        FakeResult(
            stdout=json.dumps({"desiredStatus": "RUNNING", "ssh": {"ip": "5.6.7.8", "port": 22033}})
        ),
    )


@pytest.mark.unit
def test_fallback_cloud_type_retries_pod_create_on_stockout(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    _stub_pod_create_help_probe: None,
) -> None:
    """SECURE stock-out triggers one retry with --cloud-type=COMMUNITY when fallback is set."""
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_fallback_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="__RUNPOD_DEPLOY_DONE__\n"))
    config = _write_full_config(tmp_path, storage_mode="ephemeral")
    spec = load_job_spec(config)

    run_job(
        spec,
        config_path=config,
        dry_run=False,
        offline_dry_run=False,
        fallback_cloud_type="COMMUNITY",
    )

    pod_creates = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "create"]]
    assert len(pod_creates) == 2, f"expected 2 pod create calls, got {len(pod_creates)}"
    assert "--cloud-type=SECURE" in pod_creates[0]
    assert "--cloud-type=COMMUNITY" in pod_creates[1]
    assert "stock-out on pod create; retrying with cloud_type=COMMUNITY" in caplog.text
    # Telemetry event landed in events.jsonl
    events_files = list(tmp_path.rglob("events.jsonl"))
    assert len(events_files) == 1
    events = [json.loads(line) for line in events_files[0].read_text().splitlines()]
    fallback_events = [e for e in events if e["event"] == "cloud_type_fallback"]
    assert len(fallback_events) == 1
    assert fallback_events[0]["from_cloud_type"] == "SECURE"
    assert fallback_events[0]["to_cloud_type"] == "COMMUNITY"


@pytest.mark.unit
def test_fallback_cloud_type_skipped_for_network_volume(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    _stub_pod_create_help_probe: None,
) -> None:
    """network_volume storage forces fallback to None with a WARNING (SECURE-only constraint)."""
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="__RUNPOD_DEPLOY_DONE__\n"))
    config = _write_full_config(tmp_path, storage_mode="network_volume")
    spec = load_job_spec(config)

    run_job(
        spec,
        config_path=config,
        dry_run=False,
        offline_dry_run=False,
        fallback_cloud_type="COMMUNITY",
    )

    assert "storage.mode=network_volume is SECURE-only" in caplog.text


@pytest.mark.unit
def test_fallback_cloud_type_not_triggered_without_stockout(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _stub_pod_create_help_probe: None,
) -> None:
    """When the primary cloud_type provisions cleanly, no fallback fires."""
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="__RUNPOD_DEPLOY_DONE__\n"))
    config = _write_full_config(tmp_path)
    spec = load_job_spec(config)

    run_job(
        spec,
        config_path=config,
        dry_run=False,
        offline_dry_run=False,
        fallback_cloud_type="COMMUNITY",
    )

    pod_creates = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "create"]]
    assert len(pod_creates) == 1
    assert "--cloud-type=SECURE" in pod_creates[0]
    events_files = list(tmp_path.rglob("events.jsonl"))
    if events_files:
        events = [json.loads(line) for line in events_files[0].read_text().splitlines()]
        assert not any(e["event"] == "cloud_type_fallback" for e in events)


@pytest.mark.unit
def test_fallback_cloud_type_skipped_when_matches_primary(
    fake_subprocess: FakeSubprocess,
    fake_popen: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    _stub_pod_create_help_probe: None,
) -> None:
    """fallback == spec.pod.cloud_type is a no-op with WARNING (no useful retry).

    Uses ephemeral storage so the network-volume guard (which fires earlier
    in _resolve_effective_fallback_cloud_type) doesn't pre-empt this check.
    """
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    _freeze_time(monkeypatch)
    fake_popen(returncode_val=0)
    _enqueue_runpodctl_happy_path_ephemeral(fake_subprocess)
    fake_subprocess.when(_is_monitor_tail, FakeResult(stdout="__RUNPOD_DEPLOY_DONE__\n"))
    config = _write_full_config(tmp_path, storage_mode="ephemeral")
    spec = load_job_spec(config)

    run_job(
        spec,
        config_path=config,
        dry_run=False,
        offline_dry_run=False,
        fallback_cloud_type="SECURE",  # same as spec.pod.cloud_type default
    )

    assert "matches the configured pod.cloud_type; skipped" in caplog.text
