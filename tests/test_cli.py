from __future__ import annotations

import logging
from pathlib import Path

import pytest

from runpod_deploy.cli import main


def _write_minimal_config(path: Path, *, extra: str = "") -> Path:
    path.write_text(f"""
schema_version: 1
name: demo
run_id_prefix: demo
local:
  project_root: .
  required_paths:
    - pyproject.toml
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenter_id: US-MD-1
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
    assert "schema_version=1" in caplog.text
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
    assert "runpodctl pod stop" in caplog.text


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
