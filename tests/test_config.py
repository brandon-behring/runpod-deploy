from __future__ import annotations

from pathlib import Path

import pytest

from runpod_deploy.config import (
    DEFAULT_STAGING_EXCLUDES,
    build_job_context,
    load_job_spec,
    validate_local_paths,
)


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


# ---- staging excludes defaults (issue #25) ----


_STAGING_EXTRA_TEMPLATE = """\
staging:
  - label: source
    source: "{{project_root}}/"
    destination: "/workspace/demo/"
{body}
"""


def _write_staging_config(path: Path, body: str) -> Path:
    """Minimal YAML with one staging entry; ``body`` injects extra keys."""
    return _write_minimal_config(
        path,
        extra=_STAGING_EXTRA_TEMPLATE.format(body=body),
    )


@pytest.mark.unit
def test_staging_default_excludes_off_preserves_backcompat(tmp_path: Path) -> None:
    """Existing YAMLs (excludes only, no defaults) keep current behavior."""
    config = _write_staging_config(
        tmp_path / "job.yaml",
        '    excludes: ["custom-only.bak"]\n',
    )
    spec = load_job_spec(config)
    staging = spec.staging[0]
    assert staging.excludes_default is False
    assert staging.excludes == ("custom-only.bak",)
    assert staging.excludes_extra == ()
    assert staging.effective_excludes == ("custom-only.bak",)


@pytest.mark.unit
def test_staging_default_excludes_on_prepends_hygiene_set(tmp_path: Path) -> None:
    """`excludes_default: true` prepends DEFAULT_STAGING_EXCLUDES."""
    config = _write_staging_config(
        tmp_path / "job.yaml",
        "    excludes_default: true\n",
    )
    spec = load_job_spec(config)
    staging = spec.staging[0]
    assert staging.excludes_default is True
    assert staging.effective_excludes == DEFAULT_STAGING_EXCLUDES


@pytest.mark.unit
def test_staging_default_plus_extras_merges_in_documented_order(tmp_path: Path) -> None:
    """Effective list = defaults + excludes + excludes_extra (documented order)."""
    config = _write_staging_config(
        tmp_path / "job.yaml",
        (
            "    excludes_default: true\n"
            '    excludes: ["mid.tmp"]\n'
            '    excludes_extra: ["evals/", "artifacts/"]\n'
        ),
    )
    spec = load_job_spec(config)
    staging = spec.staging[0]
    assert staging.effective_excludes == (
        *DEFAULT_STAGING_EXCLUDES,
        "mid.tmp",
        "evals/",
        "artifacts/",
    )


@pytest.mark.unit
def test_staging_excludes_extra_without_default_just_appends(tmp_path: Path) -> None:
    """`excludes_extra` alone (no defaults) still appends to `excludes`."""
    config = _write_staging_config(
        tmp_path / "job.yaml",
        ('    excludes: ["explicit.tmp"]\n' '    excludes_extra: ["evals/"]\n'),
    )
    spec = load_job_spec(config)
    staging = spec.staging[0]
    assert staging.excludes_default is False
    assert staging.effective_excludes == ("explicit.tmp", "evals/")


@pytest.mark.unit
def test_staging_unknown_key_still_rejected(tmp_path: Path) -> None:
    """Schema strictness preserved; unknown keys raise."""
    config = _write_staging_config(
        tmp_path / "job.yaml",
        "    excludes_wat: true\n",
    )
    with pytest.raises(KeyError, match=r"unknown staging\[0\] keys"):
        load_job_spec(config)


# ---- pod.python_version (issue #24) ----


@pytest.mark.unit
def test_pod_python_version_defaults_to_none(tmp_path: Path) -> None:
    """Existing YAMLs (no python_version key) get None and preserve current behavior."""
    config = _write_minimal_config(tmp_path / "job.yaml")
    spec = load_job_spec(config)
    assert spec.pod.python_version is None


@pytest.mark.unit
@pytest.mark.parametrize("version", ["3.13", "3.13.5", "3.14", "3.12.10"])
def test_pod_python_version_accepts_valid_formats(tmp_path: Path, version: str) -> None:
    """Versions matching `3.MINOR` or `3.MINOR.PATCH` are accepted."""
    config = _write_minimal_config(
        tmp_path / "job.yaml",
        extra=f'pod:\n  image: img\n  datacenters: [EU-RO-1]\n  gpu_order: [g1]\n  python_version: "{version}"\n',
    )
    # The minimal config already declares a `pod:` block; overwriting via
    # a second `pod:` mapping at top level is a duplicate-key issue. Write
    # a one-off config with the field embedded inline instead.
    config.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: [g1]
  python_version: "{version}"
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: DONE
  body: echo DONE
""")
    spec = load_job_spec(config)
    assert spec.pod.python_version == version


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "3",  # too short
        "3.13.5a1",  # pre-release suffix rejected
        "3.13rc1",
        "python3.13",
        "3.13.5.0",  # too many segments
        "",  # empty
        "3.13 ",  # trailing space
    ],
)
def test_pod_python_version_rejects_invalid_formats(tmp_path: Path, bad: str) -> None:
    """Pre-release suffixes and malformed versions are rejected for reproducibility."""
    config = tmp_path / "job.yaml"
    config.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: [g1]
  python_version: "{bad}"
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: DONE
  body: echo DONE
""")
    with pytest.raises(ValueError, match="pod.python_version must match"):
        load_job_spec(config)


@pytest.mark.unit
def test_default_staging_excludes_contents_are_hygiene_only(tmp_path: Path) -> None:
    """DEFAULT_STAGING_EXCLUDES contents lock the v0.4 contract.

    Hygiene-only (Q3 decision); project-specific entries like `artifacts/`,
    `evals/`, IDE/OS files, or `node_modules/` are intentionally NOT in
    the default — they belong in consumer `excludes_extra`.
    """
    assert DEFAULT_STAGING_EXCLUDES == (
        ".git/",
        ".venv/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".mypy_cache/",
        "**/__pycache__/",
        "**/*.pyc",
    )


# ---- v0.7 PR-N gap fill (T8) ----


@pytest.mark.unit
def test_pod_python_version_rejects_template_literal_at_parse_time(tmp_path: Path) -> None:
    """T8: validation of `pod.python_version` runs in __post_init__ (pre-render).

    The regex `^3\\.\\d+(\\.\\d+)?$` is checked against the raw string
    *as stored on the spec* — not after template-variable expansion.
    So a YAML with `python_version: "{py_ver}"` is rejected at
    parse time, even though `--var py_ver=3.13` would later render
    to a valid value. This is intentional: template-driven
    interpreter pinning conflates the "what version" decision with
    the "what variable" abstraction; reject it upfront for clarity.
    """
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: demo
run_id_prefix: demo
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: [g1]
  python_version: "{py_ver}"
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: DONE
  body: echo DONE
""")
    with pytest.raises(ValueError, match="pod.python_version must match"):
        load_job_spec(config)


# ---------- lifecycle policy parser (Phase 2 of pod-lifecycle fix) ----------


@pytest.mark.unit
def test_load_job_spec_default_lifecycle_is_delete_on_success_stop_on_failure(
    tmp_path: Path,
) -> None:
    config = _write_minimal_config(tmp_path / "job.yaml")
    spec = load_job_spec(config)
    assert spec.lifecycle.on_success == "delete"
    assert spec.lifecycle.on_failure == "stop"


@pytest.mark.unit
def test_load_job_spec_accepts_lifecycle_string_actions(tmp_path: Path) -> None:
    extra = "lifecycle:\n  on_success: preserve\n  on_failure: delete\n"
    config = _write_minimal_config(tmp_path / "job.yaml", extra=extra)
    spec = load_job_spec(config)
    assert spec.lifecycle.on_success == "preserve"
    assert spec.lifecycle.on_failure == "delete"


@pytest.mark.unit
def test_load_job_spec_rejects_invalid_lifecycle_action(tmp_path: Path) -> None:
    extra = "lifecycle:\n  on_success: explode\n"
    config = _write_minimal_config(tmp_path / "job.yaml", extra=extra)
    with pytest.raises(ValueError, match="lifecycle.on_success must be one of"):
        load_job_spec(config)


@pytest.mark.unit
def test_load_job_spec_legacy_stop_bool_shim_maps_to_lifecycle_with_deprecation(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Legacy ``stop: {on_success: true, on_failure: false}`` parses with shim.

    Mapping:
      - ``on_success: true`` → ``"delete"`` (release disk on success)
      - ``on_failure: false`` → ``"preserve"`` (legacy "don't stop")
    A single ``[deprecated]`` WARNING is emitted per parse.
    """
    import logging as _logging

    caplog.set_level(_logging.WARNING, logger="runpod_deploy")
    extra = "stop:\n  on_success: true\n  on_failure: false\n"
    config = _write_minimal_config(tmp_path / "job.yaml", extra=extra)

    spec = load_job_spec(config)

    assert spec.lifecycle.on_success == "delete"
    assert spec.lifecycle.on_failure == "preserve"
    assert "[deprecated]" in caplog.text and "stop" in caplog.text


@pytest.mark.unit
def test_load_job_spec_rejects_both_lifecycle_and_legacy_stop(tmp_path: Path) -> None:
    extra = (
        "lifecycle:\n  on_success: delete\n  on_failure: stop\n"
        "stop:\n  on_success: true\n  on_failure: true\n"
    )
    config = _write_minimal_config(tmp_path / "job.yaml", extra=extra)
    with pytest.raises(ValueError, match="both 'lifecycle' and legacy 'stop'"):
        load_job_spec(config)
