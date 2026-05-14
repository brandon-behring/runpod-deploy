from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from runpod_deploy.cli import main


def _make_manifest(parent: Path, ts: str, **fields: object) -> Path:
    run_dir = parent / "artifacts" / "runpod" / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "schema_version": "v2",
        "job_name": "demo",
        "pod_id": "abc123",
        "gpu_id": "NVIDIA H100 80GB HBM3",
        "datacenter_id": "US-GA-2",
        "wall_time_sec": 1842.4,
        "failed": False,
        "estimated_cost_usd": 2.14,
    }
    base.update(fields)
    (run_dir / "runpod_deploy_pull_manifest.json").write_text(json.dumps(base))
    return run_dir


@pytest.mark.unit
def test_ls_runs_table_lists_runs_in_chronological_order(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _make_manifest(tmp_path, "20260514T160000Z", job_name="later")
    _make_manifest(tmp_path, "20260514T120000Z", job_name="earlier")
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["ls-runs", "--project-root", str(tmp_path)])

    assert rc == 0
    out = caplog.text
    assert out.index("earlier") < out.index("later")
    assert "timestamp" in out
    assert "$2.14" in out


@pytest.mark.unit
def test_ls_runs_limit_returns_only_n_most_recent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    for i in range(5):
        _make_manifest(tmp_path, f"20260514T1{i}0000Z", job_name=f"job{i}")
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["ls-runs", "--project-root", str(tmp_path), "--limit", "2"])

    assert rc == 0
    out = caplog.text
    # Should include the two most recent (job3, job4) and exclude older ones.
    assert "job4" in out
    assert "job3" in out
    assert "job0" not in out


@pytest.mark.unit
def test_ls_runs_json_emits_array(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_manifest(tmp_path, "20260514T120000Z", job_name="demo", failed=True)

    rc = main(["ls-runs", "--project-root", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert len(payload) == 1
    assert payload[0]["job"] == "demo"
    assert payload[0]["failed"] is True


@pytest.mark.unit
def test_ls_runs_no_runs_logs_info(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["ls-runs", "--project-root", str(tmp_path)])

    assert rc == 0
    assert "no runs found" in caplog.text


@pytest.mark.unit
def test_ls_runs_handles_v1_manifest_with_missing_v2_fields(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # v1 manifest lacks wall_time_sec / estimated_cost_usd / failed.
    _make_manifest(
        tmp_path,
        "20260514T120000Z",
        schema_version="v1",
        job_name="legacy",
        wall_time_sec=None,
        estimated_cost_usd=None,
        failed=None,
    )
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["ls-runs", "--project-root", str(tmp_path)])

    assert rc == 0
    out = caplog.text
    assert "legacy" in out
    # Missing wall_time → "—" placeholder.
    assert "—" in out
