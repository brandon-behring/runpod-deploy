from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from runpod_deploy.cli import main
from tests.conftest import FakeResult, FakeSubprocess


def _write_minimal_config(path: Path, *, extra: str = "") -> Path:
    path.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
local:
  project_root: .
  required_paths:
    - pyproject.toml
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenters: [US-MD-1]
  gpu_order:
    - NVIDIA A100-SXM4-80GB
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
{extra}
""")
    return path


@pytest.mark.unit
def test_validate_ok(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = _write_minimal_config(tmp_path / "job.yaml")

    rc = main(["validate", "--config", str(config)])

    assert rc == 0
    assert "ok: " in caplog.text
    assert "schema_version=2" in caplog.text
    assert "job=demo" in caplog.text


@pytest.mark.unit
def test_validate_check_local_reports_missing_path(tmp_path: Path) -> None:
    config = _write_minimal_config(tmp_path / "job.yaml")

    with pytest.raises(FileNotFoundError, match="required local paths"):
        main(["validate", "--config", str(config), "--check-local"])


@pytest.mark.unit
def test_run_offline_dry_run_walks_command_shape(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = _write_minimal_config(
        tmp_path / "job.yaml",
        extra="""staging:
  - label: repo
    source: "{project_root}/"
    destination: "/workspace/demo/"
artifacts:
  - label: log
    remote_path: /workspace/demo.log
    local_path: "{run_dir}"
    required: false
""",
    )

    rc = main(["run", "--config", str(config), "--offline-dry-run"])

    assert rc == 0
    assert "runpodctl pod create" in caplog.text
    assert "--gpu-id 'NVIDIA A100-SXM4-80GB'" in caplog.text
    assert "rsync-push:repo" in caplog.text
    assert "ssh-detached" in caplog.text
    # New default lifecycle.on_success == "delete" — releases volume disk.
    assert "runpodctl pod delete" in caplog.text


@pytest.mark.unit
def test_quiet_flag_suppresses_info_output(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = _write_minimal_config(tmp_path / "job.yaml")

    rc = main(["validate", "--quiet", "--config", str(config)])

    assert rc == 0
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info_records == []


@pytest.mark.unit
def test_verbose_flag_enables_debug_output(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = _write_minimal_config(
        tmp_path / "job.yaml",
        extra="""staging:
  - label: repo
    source: "{project_root}/"
    destination: "/workspace/demo/"
""",
    )

    rc = main(["run", "--verbose", "--config", str(config), "--offline-dry-run"])

    assert rc == 0
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("rsync-push" in r.getMessage() for r in debug_records)


@pytest.mark.unit
def test_run_cost_cap_override_applies(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = _write_minimal_config(tmp_path / "job.yaml")

    rc = main(
        [
            "run",
            "--config",
            str(config),
            "--offline-dry-run",
            "--cost-cap-usd",
            "0.25",
        ]
    )

    assert rc == 0
    assert "cap=$0.25" in caplog.text


# ---------- logs subcommand ----------


def _write_logs_fixture_config(tmp_path: Path) -> tuple[Path, Path]:
    """Write a config + matching state file. Returns (config, state_file)."""
    state_file = tmp_path / "state.json"
    config = tmp_path / "job.yaml"
    config.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
state_file: {state_file}
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenters: [US-MD-1]
  gpu_order:
    - NVIDIA A100-SXM4-80GB
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
""")
    state_file.write_text(json.dumps({"pod_id": "pod-xyz"}))
    return config, state_file


@pytest.mark.unit
def test_logs_streams_tail_with_follow_by_default(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = _write_logs_fixture_config(tmp_path)
    fake_subprocess.enqueue(
        FakeResult(
            stdout=json.dumps({"desiredStatus": "RUNNING", "ssh": {"ip": "5.6.7.8", "port": 22033}})
        ),
        FakeResult(returncode=0),
    )
    captured: dict[str, Any] = {}

    def _spy(self: Any, command: str) -> int:
        captured["command"] = command
        return 0

    monkeypatch.setattr("runpod_deploy.cli.RemoteRunner.ssh_stream", _spy)

    rc = main(["logs", "--config", str(config)])

    assert rc == 0
    assert captured["command"] == "tail -n 200 -f /workspace/demo.log"


@pytest.mark.unit
def test_logs_no_follow_omits_f_flag(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = _write_logs_fixture_config(tmp_path)
    fake_subprocess.enqueue(
        FakeResult(
            stdout=json.dumps({"desiredStatus": "RUNNING", "ssh": {"ip": "5.6.7.8", "port": 22033}})
        ),
    )
    captured: dict[str, Any] = {}

    def _spy(self: Any, command: str) -> int:
        captured["command"] = command
        return 0

    monkeypatch.setattr("runpod_deploy.cli.RemoteRunner.ssh_stream", _spy)

    rc = main(["logs", "--config", str(config), "--no-follow", "--lines", "50"])

    assert rc == 0
    assert captured["command"] == "tail -n 50 /workspace/demo.log"


@pytest.mark.unit
def test_logs_raises_when_state_file_missing(tmp_path: Path) -> None:
    config, state_file = _write_logs_fixture_config(tmp_path)
    state_file.unlink()

    with pytest.raises(FileNotFoundError, match="state file not found"):
        main(["logs", "--config", str(config)])


@pytest.mark.unit
def test_gpu_list_prints_sorted_table(
    fake_subprocess: FakeSubprocess, caplog: pytest.LogCaptureFixture
) -> None:
    fake_subprocess.enqueue(
        FakeResult(
            stdout=json.dumps(
                [
                    {
                        "id": "EU-RO-1",
                        "gpuAvailability": [
                            {"gpuId": "NVIDIA RTX A4000", "stockStatus": "Low"},
                            {"gpuId": "NVIDIA RTX A5000", "stockStatus": "High"},
                            {"gpuId": "NVIDIA RTX A6000", "stockStatus": "Medium"},
                        ],
                    }
                ]
            )
        )
    )
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-list", "--datacenter", "EU-RO-1"])

    assert rc == 0
    messages = [r.message for r in caplog.records]
    assert "datacenter: EU-RO-1" in messages
    name_rows = [m for m in messages if m.startswith("NVIDIA")]
    assert name_rows[0].startswith("NVIDIA RTX A5000")  # High first
    assert name_rows[1].startswith("NVIDIA RTX A6000")  # Medium
    assert name_rows[2].startswith("NVIDIA RTX A4000")  # Low last


@pytest.mark.unit
def test_gpu_list_raises_when_datacenter_missing(fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.enqueue(FakeResult(stdout=json.dumps([{"id": "US-MO-1"}])))

    with pytest.raises(RuntimeError, match="datacenter 'EU-RO-1' not found"):
        main(["gpu-list", "--datacenter", "EU-RO-1"])


# ---------- --ssh-ready-timeout-sec CLI override (Issue #88) ----------


@pytest.mark.unit
def test_cli_run_propagates_ssh_ready_timeout_sec_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``runpod-deploy run --ssh-ready-timeout-sec 450`` reaches run_job."""
    config = _write_minimal_config(tmp_path / "job.yaml")
    captured: dict[str, Any] = {}

    def fake_run_job(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("runpod_deploy.cli.run_job", fake_run_job)

    rc = main(
        [
            "run",
            "--config",
            str(config),
            "--offline-dry-run",
            "--ssh-ready-timeout-sec",
            "450",
        ]
    )

    assert rc == 0
    assert captured["ssh_ready_timeout_sec_override"] == 450


@pytest.mark.unit
def test_cli_run_default_ssh_ready_timeout_override_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without the flag, the override is None so the spec default applies."""
    config = _write_minimal_config(tmp_path / "job.yaml")
    captured: dict[str, Any] = {}

    def fake_run_job(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("runpod_deploy.cli.run_job", fake_run_job)

    rc = main(["run", "--config", str(config), "--offline-dry-run"])

    assert rc == 0
    assert captured["ssh_ready_timeout_sec_override"] is None


@pytest.mark.unit
def test_cli_run_propagates_force_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``runpod-deploy run --force-fresh`` reaches run_job as force_fresh=True."""
    config = _write_minimal_config(tmp_path / "job.yaml")
    captured: dict[str, Any] = {}

    def fake_run_job(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("runpod_deploy.cli.run_job", fake_run_job)

    rc = main(["run", "--config", str(config), "--offline-dry-run", "--force-fresh"])

    assert rc == 0
    assert captured["force_fresh"] is True


@pytest.mark.unit
def test_cli_run_default_force_fresh_is_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without --force-fresh, force_fresh defaults to False."""
    config = _write_minimal_config(tmp_path / "job.yaml")
    captured: dict[str, Any] = {}

    def fake_run_job(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("runpod_deploy.cli.run_job", fake_run_job)

    rc = main(["run", "--config", str(config), "--offline-dry-run"])

    assert rc == 0
    assert captured["force_fresh"] is False
