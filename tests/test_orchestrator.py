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


@pytest.mark.smoke
def test_print_run_dir_emits_single_stdout_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--print-run-dir` emits exactly one `RUN_DIR=<path>` line on stdout.

    Contract: line appears once, on stdout (not stderr), starts with the
    literal `RUN_DIR=` prefix, and points at an `artifacts/runpod/<ts>/`
    path under the resolved project_root. Drivers grep this line per
    attempt to learn the run-dir without racing `ls -td`.
    """
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

    run_job(
        load_job_spec(config),
        config_path=config,
        offline_dry_run=True,
        print_run_dir=True,
    )

    captured = capsys.readouterr()
    run_dir_lines = [line for line in captured.out.splitlines() if line.startswith("RUN_DIR=")]
    assert (
        len(run_dir_lines) == 1
    ), f"expected exactly one RUN_DIR= line on stdout, got {run_dir_lines!r}"
    run_dir_path = run_dir_lines[0].removeprefix("RUN_DIR=")
    assert "artifacts/runpod/" in run_dir_path, run_dir_path
    assert run_dir_path.endswith("Z"), run_dir_path
    # Default (flag absent) must NOT emit the line.
    assert "RUN_DIR=" not in captured.err


@pytest.mark.smoke
def test_python_version_prepends_uv_install_pin_preflight(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`pod.python_version` set → auto-injected `uv python install + pin` runs as preflight[0].

    Contract: the rendered command logged at preflight[0] must contain
    `uv python install <ver>` and `uv python pin <ver>`, and must `cd`
    into the first staging entry's destination before the pin so the
    `.python-version` file lands in the staged project dir.
    """
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
  python_version: "3.13.5"
storage:
  mode: ephemeral
  volume_gb: 20
ssh:
  key_path: ~/.ssh/id_ed25519
setup: []
staging:
  - label: repo
    source: "{project_root}/"
    destination: "/workspace/demo/"
    excludes: [".git/"]
preflight:
  - command: "echo user-preflight"
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
artifacts: []
stop:
  on_success: true
  on_failure: true
""")
    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)
    log = caplog.text
    # Injected preflight[0] must include the install + pin commands AND
    # cd into the staging destination (so .python-version lands there).
    assert "uv python install 3.13.5" in log
    assert "uv python pin 3.13.5" in log
    assert "cd /workspace/demo/" in log
    # The user's own preflight command still runs (auto-inject prepends, not replaces).
    assert "echo user-preflight" in log


@pytest.mark.smoke
def test_python_version_absent_means_no_pin_injection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Without `pod.python_version`, no `uv python install` line appears."""
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
setup: []
staging: []
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
artifacts: []
stop:
  on_success: true
  on_failure: true
""")
    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)
    assert "uv python install" not in caplog.text
    assert "uv python pin" not in caplog.text


@pytest.mark.smoke
def test_print_run_dir_absent_by_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without `--print-run-dir`, no `RUN_DIR=` line appears anywhere."""
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
setup: []
staging: []
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
artifacts: []
stop:
  on_success: true
  on_failure: true
""")

    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)

    captured = capsys.readouterr()
    assert "RUN_DIR=" not in captured.out
    assert "RUN_DIR=" not in captured.err
