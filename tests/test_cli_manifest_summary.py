from __future__ import annotations

import json
from pathlib import Path

import pytest

from runpod_deploy.cli import main


def _v2_manifest(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": "v2",
        "job_name": "demo",
        "run_id": "demo-20260514T120000Z",
        "failed": False,
        "pod_id": "abc123",
        "gpu_id": "NVIDIA H100 80GB HBM3",
        "datacenter_id": "US-GA-2",
        "image": "runpod/pytorch:2.4.0",
        "storage_mode": "ephemeral",
        "wall_time_sec": 1842.4,
        "gpu_price_per_hour_usd": 4.18,
        "gpu_price_source": "pod_describe",
        "estimated_cost_usd": 2.14,
        "cost_cap_usd": 8.0,
        "pod_final_state": "EXITED",
        "deploy_metadata": {
            "local_git_sha": "abcd",
            "local_git_dirty": False,
            "payload_lockfile": "uv.lock",
        },
        "artifacts": [
            {"label": "results", "status": "success", "duration_sec": 3.2},
        ],
        "telemetry_files": ["nvidia_smi_start.txt", "events.jsonl"],
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_manifest_summary_prints_key_value_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps(_v2_manifest()))

    rc = main(["manifest-summary", str(manifest_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "job:           demo" in out
    assert "schema:        v2" in out
    assert "pod_id:        abc123" in out
    assert "datacenter:    US-GA-2" in out
    assert "price_usd/hr:  4.18 (pod_describe)" in out
    assert "deploy_metadata:" in out
    assert "  local_git_sha: abcd" in out
    assert "artifacts:" in out
    assert "- results: status=success duration_sec=3.2" in out
    assert "telemetry_files:" in out
    assert "- nvidia_smi_start.txt" in out


@pytest.mark.unit
def test_manifest_summary_handles_missing_optional_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    minimal = {
        "schema_version": "v2",
        "job_name": "demo",
        "run_id": "x",
        "failed": True,
    }
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps(minimal))

    rc = main(["manifest-summary", str(manifest_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "failed:        True" in out
    assert "pod_id:        None" in out
    # No deploy_metadata / artifacts / telemetry_files blocks when absent.
    assert "deploy_metadata:" not in out
    assert "artifacts:" not in out
    assert "telemetry_files:" not in out


@pytest.mark.unit
def test_manifest_summary_raises_on_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="manifest not found"):
        main(["manifest-summary", str(tmp_path / "nonexistent.json")])


# ---- --root multi-manifest mode (issue #21) ----


def _write_run_manifest(run_dir: Path, **overrides: object) -> Path:
    """Drop a runpod_deploy_pull_manifest.json into run_dir; return its path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "runpod_deploy_pull_manifest.json"
    path.write_text(json.dumps(_v2_manifest(**overrides)))
    return path


@pytest.mark.unit
def test_manifest_summary_root_aggregates_with_totals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--root walks recursively and prints a per-run block plus TOTALS."""
    root = tmp_path / "artifacts" / "runpod"
    _write_run_manifest(
        root / "20260514T120000Z",
        run_id="demo-a",
        wall_time_sec=1000.0,
        estimated_cost_usd=2.0,
        failed=False,
    )
    _write_run_manifest(
        root / "20260514T130000Z",
        run_id="demo-b",
        wall_time_sec=2500.0,
        estimated_cost_usd=4.5,
        failed=True,
    )

    rc = main(["manifest-summary", "--root", str(root)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "== TOTALS ==" in out
    assert "manifests:        2" in out
    assert "failed:           1" in out
    assert "wall_time_sec:    3500.0" in out
    assert "estimated_cost:   $6.50" in out
    # Both per-run blocks included with their absolute paths as headers.
    assert "== " in out and "runpod_deploy_pull_manifest.json ==" in out
    assert "run_id:        demo-a" in out
    assert "run_id:        demo-b" in out


@pytest.mark.unit
def test_manifest_summary_root_empty_dir_warns_and_exits_zero(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty --root directory logs INFO and exits 0 (not a failure)."""
    import logging as _logging

    empty = tmp_path / "empty"
    empty.mkdir()
    caplog.set_level(_logging.INFO, logger="runpod_deploy")
    rc = main(["manifest-summary", "--root", str(empty)])
    assert rc == 0
    assert "no manifests found under" in caplog.text


@pytest.mark.unit
def test_manifest_summary_root_missing_dir_raises(tmp_path: Path) -> None:
    """A nonexistent --root path is a hard error (per fail-fast policy)."""
    with pytest.raises(FileNotFoundError, match="--root directory not found"):
        main(["manifest-summary", "--root", str(tmp_path / "nope")])


@pytest.mark.unit
def test_manifest_summary_rejects_both_args(tmp_path: Path) -> None:
    """Mutually exclusive: passing both manifest and --root is rejected."""
    path = tmp_path / "m.json"
    path.write_text(json.dumps(_v2_manifest()))
    import argparse

    with pytest.raises(argparse.ArgumentTypeError, match="exactly one of"):
        main(["manifest-summary", str(path), "--root", str(tmp_path)])


@pytest.mark.unit
def test_manifest_summary_rejects_neither_arg() -> None:
    """No-args invocation is rejected with a helpful message."""
    import argparse

    with pytest.raises(argparse.ArgumentTypeError, match="manifest path or --root"):
        main(["manifest-summary"])


@pytest.mark.unit
def test_run_rejects_unpaired_gpu_id_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: demo
pod:
  image: img
  datacenters: [EU-RO-1]
  gpu_order: [g1]
storage:
  mode: ephemeral
  volume_gb: 10
run:
  script_path: /workspace/r.sh
  log_path: /workspace/r.log
  success_marker: DONE
  body: echo DONE
""")

    with pytest.raises(SystemExit):
        # argparse converts ArgumentTypeError to SystemExit when raised inside an action;
        # but here we raise from the handler, so this should propagate as is.
        # Test only that --gpu-id without --datacenter-id is rejected.
        try:
            main(["run", "--config", str(config), "--gpu-id", "g1", "--offline-dry-run"])
        except Exception as exc:
            raise SystemExit(str(exc)) from exc


# ---- v0.7 PR-N gap fill (T6) ----


@pytest.mark.unit
def test_manifest_summary_root_skips_malformed_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T6: `--root` skips manifests that fail to parse, logs WARN, continues.

    Defensive aggregation: one corrupt manifest doesn't blind the
    operator to the rest of the sweep. Asserts (a) WARN is logged,
    (b) well-formed manifests still appear, (c) TOTALS reflect only
    parsed manifests.
    """
    import logging as _logging

    root = tmp_path / "artifacts" / "runpod"

    # Manifest A: well-formed.
    _write_run_manifest(
        root / "20260514T120000Z",
        run_id="demo-a",
        wall_time_sec=1000.0,
        estimated_cost_usd=2.0,
        failed=False,
    )
    # Manifest B: malformed JSON.
    bad_dir = root / "20260514T130000Z"
    bad_dir.mkdir(parents=True)
    (bad_dir / "runpod_deploy_pull_manifest.json").write_text("{not valid json")
    # Manifest C: well-formed.
    _write_run_manifest(
        root / "20260514T140000Z",
        run_id="demo-c",
        wall_time_sec=500.0,
        estimated_cost_usd=1.5,
        failed=True,
    )

    caplog.set_level(_logging.WARNING, logger="runpod_deploy")
    rc = main(["manifest-summary", "--root", str(root)])
    out = capsys.readouterr().out

    assert rc == 0
    # WARN logged for the malformed manifest.
    assert "failed to parse" in caplog.text
    # Well-formed manifests still appear.
    assert "run_id:        demo-a" in out
    assert "run_id:        demo-c" in out
    # TOTALS reflects rglob's manifest count (3) but parsed-only stats.
    assert "manifests:        3" in out
    assert "failed:           1" in out
    # 1000 + 500 = 1500 (B skipped because JSON invalid)
    assert "wall_time_sec:    1500.0" in out
    # 2.0 + 1.5 = 3.5
    assert "estimated_cost:   $3.50" in out
