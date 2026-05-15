"""End-to-end integration tests via `--offline-dry-run`.

Each test exercises the full `run_job` lifecycle (validate → provision
sentinel → SSH no-op → setup → stage → preflight → launch → monitor →
pull → stop → manifest-write) under `offline_dry_run=True`. No external
calls; everything is logged. These tests catch *cross-feature*
regressions that the per-PR unit tests miss.

I1: composed v0.4+v0.5 features in one config (the realistic case).
I2: minimum-viable config (catches assume-non-empty regressions).
I3: max-coverage config (every optional field set to a non-default).

All marked `@pytest.mark.smoke` (runs in default `make test`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from runpod_deploy.config import load_job_spec
from runpod_deploy.orchestrator import run_job

# ---- I1: composed v0.4+v0.5 features ----


@pytest.mark.smoke
def test_integration_composed_v0_4_and_v0_5_features(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every v0.4 + v0.5 feature toggled in one --offline-dry-run.

    Exercises (and asserts each signature in the log/stdout):
    - `--var seed=42` template injection (v0.3.1)
    - rendered `name: composed-{seed}` → pod --name `composed-42-<ts>` (v0.4 PR-C)
    - rendered `run_id_prefix: composed-{seed}` → ctx.run_id (v0.4 PR-C)
    - `--print-run-dir` emits the RUN_DIR= stdout line (v0.4 PR-B)
    - rendered `run.script_path` / `log_path` / `success_marker` (v0.3.3)
    - `staging.excludes_default: true` + `excludes_extra` merge (v0.4 PR-D)
    - `pod.python_version: 3.13.5` auto-injects uv install + pin at preflight[0] (v0.5 PR-G)
    """
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: composed-{seed}
run_id_prefix: composed-{seed}
state_file: ~/.runpod-composed-current
local:
  project_root: .
  required_paths:
    - pyproject.toml
pod:
  image: runpod/pytorch:2.4.0-py3.13-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EU-RO-1, US-CA-2]
  gpu_order:
    - NVIDIA H100 80GB HBM3
  cloud_type: SECURE
  python_version: "3.13.5"
storage:
  mode: ephemeral
  volume_gb: 20
ssh:
  key_path: ~/.ssh/id_ed25519
setup:
  - command: "mkdir -p /workspace/composed"
    timeout_sec: 30
staging:
  - label: source
    source: "{project_root}/"
    destination: "/workspace/composed/"
    excludes_default: true
    excludes_extra: ["evals/", "artifacts/"]
preflight:
  - command: "cd /workspace/composed && uv sync"
    timeout_sec: 1800
run:
  script_path: /workspace/run-composed-s{seed}.sh
  log_path: /workspace/run-composed-s{seed}.log
  success_marker: "[composed-s{seed}] DONE"
  body: |
    echo "[composed-s{seed}] DONE"
artifacts:
  - label: log
    remote_path: "/workspace/run-composed-s{seed}.log"
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
        cli_variables={"seed": "42"},
    )

    log = caplog.text

    # v0.4 PR-C: pod --name carries the rendered run_id (composed-42-<ts>)
    assert "--name composed-42-" in log, log[:500]
    assert "--name composed-{seed}-" not in log

    # v0.4 PR-B: RUN_DIR= line on stdout (NOT in logger)
    captured = capsys.readouterr()
    run_dir_lines = [line for line in captured.out.splitlines() if line.startswith("RUN_DIR=")]
    assert len(run_dir_lines) == 1, run_dir_lines

    # v0.3.3: rendered run.script_path / log_path
    assert "/workspace/run-composed-s42.sh" in log
    assert "/workspace/run-composed-s42.log" in log
    assert "{seed}" not in log.replace("--var seed=42", "")  # no raw {seed} leaks

    # v0.4 PR-D: excludes_default contributions appear (e.g. .git/)
    # The staging push log includes the rendered effective_excludes tuple.
    assert ".git/" in log
    assert "evals/" in log

    # v0.5 PR-G: python_version auto-injected as preflight[0]
    assert "uv python install 3.13.5" in log
    assert "uv python pin 3.13.5" in log
    # Pin runs in /workspace/composed/ (the first staging destination).
    assert "cd /workspace/composed/" in log

    # The user's own preflight still runs.
    assert "uv sync" in log


# ---- I2: minimum-viable config ----


@pytest.mark.smoke
def test_integration_minimum_viable_config(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Smallest possible valid config still walks --offline-dry-run cleanly.

    Catches regressions where a new feature assumes a non-empty list
    (e.g., `_push_workspace` iterating over `spec.staging`, or
    `_run_commands` over `spec.setup` / `spec.preflight`). Each of
    those should be a no-op on an empty tuple, not raise.
    """
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: minimal
run_id_prefix: minimal
state_file: ~/.runpod-minimal-current
local:
  project_root: .
  required_paths:
    - pyproject.toml
pod:
  image: runpod/pytorch:2.4.0-py3.13-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EU-RO-1]
  gpu_order:
    - NVIDIA RTX A4000
storage:
  mode: ephemeral
  volume_gb: 20
ssh:
  key_path: ~/.ssh/id_ed25519
setup: []
staging: []
run:
  script_path: /workspace/minimal.sh
  log_path: /workspace/minimal.log
  success_marker: "[minimal] DONE"
  body: |
    echo "[minimal] DONE"
artifacts: []
stop:
  on_success: true
  on_failure: true
""")
    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)

    log = caplog.text
    assert "runpodctl pod create" in log
    assert "runpodctl pod stop" in log
    # No setup / staging / preflight / artifact-pull log entries should
    # have raised (each is a no-op on its empty tuple).


# ---- I3: max-coverage config ----


@pytest.mark.smoke
def test_integration_max_coverage_all_optional_fields_set(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Every optional field set to a non-default value walks cleanly.

    This is the "schema-surface smoke test" — verifies that no field
    interaction breaks under offline_dry_run when consumers opt into
    every available feature.
    """
    caplog.set_level(logging.INFO, logger="runpod_deploy")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: maxcoverage
run_id_prefix: maxcov
state_file: ~/.runpod-maxcov-current
local:
  project_root: .
  required_paths:
    - pyproject.toml
variables:
  data_dir: "{project_root}/data"
  experiment: maxcov-trial1
pod:
  image: runpod/pytorch:2.4.0-py3.13-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EU-RO-1, US-CA-2, US-GA-2]
  gpu_order:
    - NVIDIA H100 80GB HBM3
    - NVIDIA A100-SXM4-80GB
  cloud_type: SECURE
  ports: ["22/tcp", "8080/http"]
  container_disk_gb: 50
  gpu_count: 1
  spot: false
  min_vcpu_count: 8
  min_memory_gb: 32
  python_version: "3.13.5"
storage:
  mode: network_volume
  volume_name: maxcov-vol
  volume_mount: /workspace
ssh:
  key_path: ~/.ssh/id_ed25519
budget:
  cost_cap_usd: 10.0
  max_runtime_minutes: 120
  assumed_hourly_rate_usd: 4.5
  poll_interval_sec: 60
remote_env:
  exports:
    DEMO_VAR: hello
  source_files:
    - /workspace/secrets/env
setup:
  - command: "which rsync"
    timeout_sec: 60
  - command: "mkdir -p /workspace/maxcov"
    timeout_sec: 30
staging:
  - label: source
    source: "{project_root}/"
    destination: "/workspace/maxcov/"
    excludes_default: true
    excludes_extra: ["evals/", "artifacts/"]
    delete: true
preflight:
  - command: "cd /workspace/maxcov && uv sync"
    timeout_sec: 1800
    with_env: true
run:
  script_path: /workspace/maxcov.sh
  log_path: /workspace/maxcov.log
  success_marker: "[maxcov] DONE"
  failure_markers:
    - "[maxcov] ERROR"
    - "FATAL"
  body: |
    set -euo pipefail
    cd /workspace/maxcov
    echo "[maxcov] DONE"
artifacts:
  - label: log
    remote_path: /workspace/maxcov.log
    local_path: "{run_dir}/maxcov.log"
    required: false
  - label: results
    remote_path: /workspace/maxcov/results/
    local_path: "{run_dir}/results"
    required: true
    excludes: ["**/_trainer/*"]
    delete: false
telemetry:
  enabled: true
  sample_interval_sec: 30
  capture_nvidia_smi: true
  capture_dmesg: true
  capture_pod_describe: true
  capture_remote_env: true
  capture_local_git: true
  capture_payload_lockfile: true
stop:
  on_success: true
  on_failure: false
""")
    run_job(load_job_spec(config), config_path=config, offline_dry_run=True)

    log = caplog.text
    # Provision walks; staging push appears; preflight + run scripts emit.
    assert "runpodctl pod create" in log
    assert "rsync-push:source" in log
    assert "uv python install 3.13.5" in log  # python_version is set
    # stop.on_failure=false → "pod preserved" path NOT exercised on this
    # success-path test; instead stop.on_success=true triggers stop.
    assert "runpodctl pod stop" in log


# ---- Convergence: same fixture invariants ----


@pytest.mark.smoke
def test_integration_print_run_dir_path_is_under_project_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The RUN_DIR= path (when --print-run-dir is set) lives under project_root/artifacts/runpod/.

    Regression for the path-resolution contract that all three CLIs
    + integration paths agree on. Operators rely on this layout
    when grepping multiple shards' stdouts.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: pathcheck
run_id_prefix: pathcheck
state_file: ~/.runpod-pathcheck-current
local:
  project_root: .
  required_paths:
    - pyproject.toml
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: [g1]
storage:
  mode: ephemeral
  volume_gb: 20
ssh:
  key_path: ~/.ssh/id_ed25519
setup: []
staging: []
run:
  script_path: /workspace/r.sh
  log_path: /workspace/r.log
  success_marker: DONE
  body: echo DONE
artifacts: []
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
    assert len(run_dir_lines) == 1
    path = run_dir_lines[0].removeprefix("RUN_DIR=")
    # Layout invariant: project_root/artifacts/runpod/<ts>/.
    assert "/artifacts/runpod/" in path, path
    # Path is absolute (orchestrator resolves it pre-emit).
    assert path.startswith("/"), path


# ---- Sanity: integration suite is non-trivial ----


def test_integration_module_loads() -> None:
    """Importability check; catches accidental import-time regressions."""
    import tests.test_integration as _

    assert hasattr(_, "test_integration_composed_v0_4_and_v0_5_features")


_ = json  # silence unused-import warnings if json is referenced lazily
