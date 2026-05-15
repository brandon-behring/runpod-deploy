"""R1: --var KEY=VALUE and --vars-file template-variable injection.

Covers:
- CLI parse helpers: _parse_var_arg, _load_vars_file, _merge_cli_variables.
- build_job_context cli_variables plumbing (YAML override, render against
  built-ins + earlier vars, unbound {var} surface).
- End-to-end CLI integration via argparse.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from runpod_deploy.cli import (
    _load_vars_file,
    _merge_cli_variables,
    _parse_var_arg,
)
from runpod_deploy.config import build_job_context, load_job_spec


def _write_config(path: Path, *, extra: str = "") -> Path:
    """Minimal valid v2 YAML; ``extra`` injects extra top-level YAML."""
    path.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
local:
  project_root: .
  required_paths: []
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


# ---- _parse_var_arg ----


@pytest.mark.unit
def test_parse_var_arg_happy_path() -> None:
    assert _parse_var_arg("seed=42") == ("seed", "42")


@pytest.mark.unit
def test_parse_var_arg_value_may_contain_equals() -> None:
    # `partition` splits on the FIRST '=' so the rest of the value is preserved.
    assert _parse_var_arg("url=https://x.y?k=v") == ("url", "https://x.y?k=v")


@pytest.mark.unit
def test_parse_var_arg_empty_value_allowed() -> None:
    # Setting a var to empty string is legitimate (e.g., feature-flag off).
    assert _parse_var_arg("flag=") == ("flag", "")


@pytest.mark.unit
def test_parse_var_arg_rejects_missing_equals() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="KEY=VALUE form"):
        _parse_var_arg("seed42")


@pytest.mark.unit
def test_parse_var_arg_rejects_invalid_key_starts_with_digit() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="valid identifier"):
        _parse_var_arg("2seed=42")


@pytest.mark.unit
def test_parse_var_arg_rejects_invalid_key_with_dash() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="valid identifier"):
        _parse_var_arg("my-seed=42")


@pytest.mark.unit
def test_parse_var_arg_rejects_empty_key() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="valid identifier"):
        _parse_var_arg("=42")


# ---- _load_vars_file ----


@pytest.mark.unit
def test_load_vars_file_happy_path(tmp_path: Path) -> None:
    path = tmp_path / "vars.json"
    path.write_text(json.dumps({"seed": "42", "backbone": "deberta"}))
    assert _load_vars_file(path) == {"seed": "42", "backbone": "deberta"}


@pytest.mark.unit
def test_load_vars_file_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="--vars-file path does not exist"):
        _load_vars_file(tmp_path / "missing.json")


@pytest.mark.unit
def test_load_vars_file_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "vars.json"
    path.write_text("not json {")
    with pytest.raises(ValueError, match="not valid JSON"):
        _load_vars_file(path)


@pytest.mark.unit
def test_load_vars_file_rejects_non_object_root(tmp_path: Path) -> None:
    path = tmp_path / "vars.json"
    path.write_text(json.dumps(["seed", "42"]))
    with pytest.raises(TypeError, match="JSON root must be an object"):
        _load_vars_file(path)


@pytest.mark.unit
def test_load_vars_file_rejects_invalid_key(tmp_path: Path) -> None:
    path = tmp_path / "vars.json"
    path.write_text(json.dumps({"my-seed": "42"}))
    with pytest.raises(ValueError, match="must be a valid identifier"):
        _load_vars_file(path)


@pytest.mark.unit
def test_load_vars_file_rejects_non_string_value(tmp_path: Path) -> None:
    path = tmp_path / "vars.json"
    path.write_text(json.dumps({"seed": 42}))  # int, not str
    with pytest.raises(TypeError, match="must be a string"):
        _load_vars_file(path)


# ---- _merge_cli_variables ----


@pytest.mark.unit
def test_merge_cli_variables_empty() -> None:
    assert _merge_cli_variables(None, None) == {}


@pytest.mark.unit
def test_merge_cli_variables_only_cli_args() -> None:
    assert _merge_cli_variables([("seed", "42"), ("backbone", "deberta")], None) == {
        "seed": "42",
        "backbone": "deberta",
    }


@pytest.mark.unit
def test_merge_cli_variables_only_vars_file(tmp_path: Path) -> None:
    path = tmp_path / "v.json"
    path.write_text(json.dumps({"seed": "1", "epochs": "5"}))
    assert _merge_cli_variables(None, path) == {"seed": "1", "epochs": "5"}


@pytest.mark.unit
def test_merge_cli_variables_cli_overrides_vars_file(tmp_path: Path) -> None:
    path = tmp_path / "v.json"
    path.write_text(json.dumps({"seed": "42", "epochs": "5"}))
    merged = _merge_cli_variables([("seed", "43")], path)
    assert merged == {"seed": "43", "epochs": "5"}, "CLI --var must win over --vars-file"


# ---- build_job_context cli_variables plumbing ----


@pytest.mark.unit
def test_build_job_context_with_no_cli_variables(tmp_path: Path) -> None:
    """No cli_variables → built-ins only."""
    config_path = _write_config(tmp_path / "job.yaml")
    spec = load_job_spec(config_path)
    ctx = build_job_context(spec, config_path)
    assert "seed" not in ctx.variables
    assert ctx.variables["job_name"] == "demo"
    assert "project_root" in ctx.variables


@pytest.mark.unit
def test_build_job_context_cli_variable_is_added(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "job.yaml")
    spec = load_job_spec(config_path)
    ctx = build_job_context(spec, config_path, cli_variables={"seed": "42"})
    assert ctx.variables["seed"] == "42"


@pytest.mark.unit
def test_build_job_context_cli_overrides_yaml_variables(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "job.yaml",
        extra='variables:\n  seed: "99"\n  fixed: "yes"\n',
    )
    spec = load_job_spec(config_path)
    ctx = build_job_context(spec, config_path, cli_variables={"seed": "42"})
    assert ctx.variables["seed"] == "42", "CLI --var must override YAML variables: block"
    assert ctx.variables["fixed"] == "yes", "YAML vars not touched by CLI must survive"


@pytest.mark.unit
def test_build_job_context_cli_variable_can_reference_builtins(tmp_path: Path) -> None:
    """A CLI variable's value may include {project_root} / {run_id} etc."""
    config_path = _write_config(tmp_path / "job.yaml")
    spec = load_job_spec(config_path)
    ctx = build_job_context(
        spec, config_path, cli_variables={"out_dir": "{project_root}/v5/seed42"}
    )
    project_root = ctx.variables["project_root"]
    assert ctx.variables["out_dir"] == f"{project_root}/v5/seed42"


@pytest.mark.unit
def test_build_job_context_cli_variable_can_reference_yaml_variable(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "job.yaml",
        extra='variables:\n  base: "/workspace/v5"\n',
    )
    spec = load_job_spec(config_path)
    ctx = build_job_context(spec, config_path, cli_variables={"shard_dir": "{base}/seed42"})
    assert ctx.variables["shard_dir"] == "/workspace/v5/seed42"


@pytest.mark.unit
def test_build_job_context_unbound_var_reference_raises(tmp_path: Path) -> None:
    """A CLI var that references an undefined name surfaces a KeyError."""
    config_path = _write_config(tmp_path / "job.yaml")
    spec = load_job_spec(config_path)
    with pytest.raises(KeyError, match="unknown template variable"):
        build_job_context(spec, config_path, cli_variables={"x": "{undefined}"})


@pytest.mark.unit
def test_build_job_context_empty_cli_variables_no_effect(tmp_path: Path) -> None:
    """cli_variables={} is equivalent to cli_variables=None."""
    config_path = _write_config(tmp_path / "job.yaml")
    spec = load_job_spec(config_path)
    ctx = build_job_context(spec, config_path, cli_variables={})
    # Built-ins still present; no extra keys.
    user_keys = set(ctx.variables) - {
        "config_dir",
        "project_root",
        "run_dir",
        "run_id",
        "job_name",
        "volume_mount",
    }
    assert user_keys == set()


@pytest.mark.unit
def test_run_path_fields_render_cli_variables(tmp_path: Path) -> None:
    """`run.script_path` / `run.log_path` / `run.success_marker` get CLI-var expansion.

    Regression for the v0.3.2 bug where MIGRATION.md promised template
    support for ``run.script_path`` / ``run.log_path`` but the orchestrator
    used the raw strings literally — so ``{seed}`` survived as a literal
    sub-string in pod-side ssh commands and the polling marker.
    """
    config_path = tmp_path / "job.yaml"
    config_path.write_text("""
schema_version: 2
name: demo
run_id_prefix: demo
local:
  project_root: .
  required_paths: []
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: ["gpu-a"]
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/run-s{seed}.sh
  log_path: /workspace/run-s{seed}.log
  success_marker: "job-s{seed} DONE"
  body: |
    echo job-s{seed} DONE
""")
    spec = load_job_spec(config_path)
    # Spec values are stored raw (bug was in *use*, not *parse*).
    assert spec.run.script_path == "/workspace/run-s{seed}.sh"
    assert spec.run.log_path == "/workspace/run-s{seed}.log"
    assert spec.run.success_marker == "job-s{seed} DONE"
    # Rendering with --var seed=42 expands.
    ctx = build_job_context(spec, config_path, cli_variables={"seed": "42"})
    assert ctx.render(spec.run.script_path) == "/workspace/run-s42.sh"
    assert ctx.render(spec.run.log_path) == "/workspace/run-s42.log"
    assert ctx.render(spec.run.success_marker) == "job-s42 DONE"


@pytest.mark.unit
def test_name_and_run_id_prefix_render_cli_variables(tmp_path: Path) -> None:
    """`name` and `run_id_prefix` top-level YAML fields get CLI-var expansion.

    Regression for #18: v0.3.3 fixed rendering for the four `run.*` path /
    marker fields but left `name` and `run_id_prefix` raw — so a YAML with
    ``name: demo-{seed}`` produced a pod named literally ``demo-{seed}``
    (the literal substring survived into ``runpodctl pod create --name``
    via ``ctx.run_id``). build_job_context now renders both against the
    fully-merged variables dict.
    """
    config_path = tmp_path / "job.yaml"
    config_path.write_text("""
schema_version: 2
name: demo-{seed}
run_id_prefix: demo-{backbone}
local:
  project_root: .
  required_paths: []
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: ["gpu-a"]
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "DONE"
  body: |
    echo DONE
""")
    spec = load_job_spec(config_path)
    # Spec values are stored raw.
    assert spec.name == "demo-{seed}"
    assert spec.run_id_prefix == "demo-{backbone}"

    ctx = build_job_context(spec, config_path, cli_variables={"seed": "42", "backbone": "deberta"})
    # `ctx.variables["job_name"]` is the rendered name (used by user
    # configs that reference {job_name} elsewhere).
    assert ctx.variables["job_name"] == "demo-42"
    # `ctx.run_id` is the rendered run_id_prefix + timestamp (used by
    # provider.py:285 to set `runpodctl pod create --name <run_id>`).
    assert ctx.run_id.startswith("demo-deberta-")
    assert "{backbone}" not in ctx.run_id
    # `ctx.variables["run_id"]` matches `ctx.run_id`.
    assert ctx.variables["run_id"] == ctx.run_id


@pytest.mark.unit
def test_run_id_prefix_default_to_name_also_renders(tmp_path: Path) -> None:
    """When `run_id_prefix` is omitted, it defaults to `name` — which must
    also be rendered (the default-assignment happens in __post_init__
    before any rendering, so the prefix inherits the raw name template)."""
    config_path = tmp_path / "job.yaml"
    config_path.write_text("""
schema_version: 2
name: demo-{seed}
local:
  project_root: .
  required_paths: []
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: ["gpu-a"]
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "DONE"
  body: |
    echo DONE
""")
    spec = load_job_spec(config_path)
    assert spec.name == "demo-{seed}"
    assert spec.run_id_prefix == "demo-{seed}"  # defaulted from name

    ctx = build_job_context(spec, config_path, cli_variables={"seed": "7"})
    assert ctx.variables["job_name"] == "demo-7"
    assert ctx.run_id.startswith("demo-7-")
    assert "{seed}" not in ctx.run_id
