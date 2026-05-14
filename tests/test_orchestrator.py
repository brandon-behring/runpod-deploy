from __future__ import annotations

import logging
from pathlib import Path

import pytest

from runpod_deploy.config import load_job_spec
from runpod_deploy.orchestrator import run_job


@pytest.mark.smoke
def test_offline_dry_run_walks_command_shape(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: demo
state_file: ~/.runpod-demo-current
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
ssh:
  key_path: ~/.ssh/id_ed25519
setup:
  - command: "mkdir -p /workspace/demo"
staging:
  - label: repo
    source: "{project_root}/"
    destination: "/workspace/demo/"
    excludes: [".git/"]
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
artifacts:
  - label: log
    remote_path: /workspace/demo.log
    local_path: "{run_dir}"
    required: false
stop:
  on_success: true
  on_failure: true
""")

    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)

    assert "runpodctl pod create" in caplog.text
    assert "--ports 22/tcp" in caplog.text
    assert "rsync-push:repo" in caplog.text
    assert "ssh-detached" in caplog.text
    assert "dry-run" in caplog.text
    assert "runpodctl pod stop" in caplog.text
