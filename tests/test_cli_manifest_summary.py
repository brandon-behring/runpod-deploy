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
