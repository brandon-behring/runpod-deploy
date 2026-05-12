"""End-to-end orchestrator tests; mock provider+transport subprocess calls in one go."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from runpod_deploy import orchestrator
from runpod_deploy.config import load_job_spec
from runpod_deploy.orchestrator import run_job
from runpod_deploy.transport import RemoteRunner
from tests.conftest import FakeResult, FakeSubprocess


def _write_full_config(
    tmp_path: Path,
    *,
    storage_mode: str = "network_volume",
    cost_cap_usd: float = 50.0,
    hourly_rate_usd: float = 2.0,
    max_runtime_minutes: int = 30,
    poll_interval_sec: int = 5,
    on_success: bool = True,
    on_failure: bool = True,
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
schema_version: 1
name: demo
run_id_prefix: demo
state_file: {state_file}
local:
  project_root: {project}
ssh:
  key_path: {ssh_key}
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenter_id: US-MD-1
  gpu_order:
    - NVIDIA A100-SXM4-80GB
{storage_block}budget:
  cost_cap_usd: {cost_cap_usd}
  assumed_hourly_rate_usd: {hourly_rate_usd}
  max_runtime_minutes: {max_runtime_minutes}
  poll_interval_sec: {poll_interval_sec}
run:
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
stop:
  on_success: {str(on_success).lower()}
  on_failure: {str(on_failure).lower()}
""")
    return config


def _enqueue_runpodctl_happy_path(fake: FakeSubprocess) -> None:
    fake.enqueue(
        FakeResult(
            stdout=json.dumps([{"id": "vol-1", "name": "my-vol", "dataCenterId": "US-MD-1"}])
        ),
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
    assert any("runpodctl pod stop pod-xyz" in s for s in argv_strs)
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
def test_run_job_failure_marker_preserves_pod_when_on_failure_false(
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
    config = _write_full_config(tmp_path, on_failure=False)
    spec = load_job_spec(config)

    with pytest.raises(RuntimeError, match="failure marker"):
        run_job(spec, config_path=config, dry_run=False, offline_dry_run=False)

    assert "[warn] pod preserved" in caplog.text
    stop_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "stop"]]
    assert stop_calls == []


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
