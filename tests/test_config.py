from __future__ import annotations

from pathlib import Path

import pytest

from runpod_deploy.config import build_job_context, load_job_spec, validate_local_paths


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
  datacenters: [EU-RO-1]
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
def test_load_job_spec_rejects_unknown_root_key(tmp_path: Path) -> None:
    config = _write_minimal_config(tmp_path / "job.yaml", extra="surprise: true\n")

    with pytest.raises(KeyError, match="unknown root keys"):
        load_job_spec(config)


@pytest.mark.unit
def test_build_context_resolves_project_root_and_templates(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    config = _write_minimal_config(tmp_path / "job.yaml")
    spec = load_job_spec(config)
    ctx = build_job_context(spec, config)

    validate_local_paths(ctx)
    assert ctx.render("{project_root}/x").endswith("/x")
    assert ctx.run_id.startswith("demo-")


@pytest.mark.unit
def test_validate_local_paths_reports_missing_path(tmp_path: Path) -> None:
    config = _write_minimal_config(tmp_path / "job.yaml")
    spec = load_job_spec(config)
    ctx = build_job_context(spec, config)

    with pytest.raises(FileNotFoundError, match="required local paths"):
        validate_local_paths(ctx)


@pytest.mark.unit
def test_examples_are_schema_valid() -> None:
    repo = Path(__file__).resolve().parents[1]
    for config in sorted((repo / "examples").glob("**/*.yaml")):
        load_job_spec(config)


@pytest.mark.unit
def test_run_spec_accepts_templated_script_path(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: demo
run_id_prefix: demo
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EU-RO-1]
  gpu_order:
    - NVIDIA A100-SXM4-80GB
storage:
  mode: network_volume
  volume_name: vol
  volume_mount: /workspace
run:
  script_path: "{volume_mount}/demo.sh"
  log_path: "{volume_mount}/demo.log"
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
""")

    spec = load_job_spec(config)

    assert spec.run.script_path == "{volume_mount}/demo.sh"
    assert spec.run.log_path == "{volume_mount}/demo.log"


@pytest.mark.unit
def test_build_context_rejects_project_root_resolving_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    config = _write_minimal_config(tmp_path / "job.yaml")
    spec = load_job_spec(config)

    with pytest.raises(ValueError, match="project_root resolved to .HOME"):
        build_job_context(spec, config)


@pytest.mark.unit
def test_run_spec_rejects_relative_script_path(tmp_path: Path) -> None:
    config = _write_minimal_config(
        tmp_path / "job.yaml",
        extra="",
    )
    config.write_text(config.read_text().replace("/workspace/demo.sh", "relative.sh"))

    with pytest.raises(ValueError, match="run.script_path must be absolute or a template"):
        load_job_spec(config)
