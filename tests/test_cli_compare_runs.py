from __future__ import annotations

import json
from pathlib import Path

import pytest

from runpod_deploy.cli import main


def _write_manifest(path: Path, **fields: object) -> Path:
    base: dict[str, object] = {
        "schema_version": "v2",
        "job_name": "demo",
        "failed": False,
        "pod_id": "abc",
        "gpu_id": "H100",
        "datacenter_id": "US-GA-2",
        "wall_time_sec": 1842.4,
        "estimated_cost_usd": 2.14,
        "gpu_price_per_hour_usd": 4.18,
        "gpu_price_source": "pod_describe",
        "pod_final_state": "EXITED",
        "image": "img",
        "storage_mode": "ephemeral",
        "deploy_metadata": {
            "local_git_sha": "abc",
            "local_git_dirty": False,
            "local_git_branch": "main",
            "payload_lockfile": "uv.lock",
            "payload_lockfile_sha256": "sha1",
        },
        "artifacts": [
            {
                "label": "results",
                "status": "success",
                "bytes_transferred": 1048576,
                "duration_sec": 3.2,
            }
        ],
    }
    base.update(fields)
    path.write_text(json.dumps(base))
    return path


@pytest.mark.unit
def test_compare_runs_marks_changed_fields_with_arrow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write_manifest(tmp_path / "a.json", gpu_id="H100", wall_time_sec=1800.0)
    b = _write_manifest(tmp_path / "b.json", gpu_id="A100", wall_time_sec=1850.0)

    rc = main(["compare-runs", str(a), str(b)])
    out = capsys.readouterr().out

    assert rc == 0  # neither failed
    assert "H100  →  A100" in out
    assert "1800.0  →  1850.0" in out  # _render_value uses .1f for |v| >= 1000
    # Unchanged fields show with ==
    assert "demo == demo" in out  # job_name


@pytest.mark.unit
def test_compare_runs_diffs_deploy_metadata(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write_manifest(
        tmp_path / "a.json",
        deploy_metadata={
            "local_git_sha": "abc",
            "local_git_dirty": False,
            "local_git_branch": "main",
            "payload_lockfile": "uv.lock",
            "payload_lockfile_sha256": "sha1",
        },
    )
    b = _write_manifest(
        tmp_path / "b.json",
        deploy_metadata={
            "local_git_sha": "def",
            "local_git_dirty": True,
            "local_git_branch": "main",
            "payload_lockfile": "uv.lock",
            "payload_lockfile_sha256": "sha2",
        },
    )

    main(["compare-runs", str(a), str(b)])
    out = capsys.readouterr().out

    assert "deploy_metadata.local_git_sha" in out
    assert "abc  →  def" in out
    assert "False  →  True" in out  # local_git_dirty changed
    assert "sha1  →  sha2" in out


@pytest.mark.unit
def test_compare_runs_diffs_per_artifact_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write_manifest(
        tmp_path / "a.json",
        artifacts=[
            {"label": "results", "status": "success", "duration_sec": 3.2},
        ],
    )
    b = _write_manifest(
        tmp_path / "b.json",
        artifacts=[
            {"label": "results", "status": "failed", "duration_sec": 1.1, "error": "rsync 23"},
        ],
    )

    main(["compare-runs", str(a), str(b)])
    out = capsys.readouterr().out

    assert "artifact[results].status" in out
    assert "success  →  failed" in out


@pytest.mark.unit
def test_compare_runs_handles_artifacts_only_in_one_side(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write_manifest(
        tmp_path / "a.json",
        artifacts=[{"label": "old-only", "status": "success"}],
    )
    b = _write_manifest(
        tmp_path / "b.json",
        artifacts=[{"label": "new-only", "status": "success"}],
    )

    main(["compare-runs", str(a), str(b)])
    out = capsys.readouterr().out

    # Both labels show; the missing-side renders as "—".
    assert "artifact[old-only].status" in out
    assert "artifact[new-only].status" in out


@pytest.mark.unit
def test_compare_runs_exits_1_on_any_failed_true(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write_manifest(tmp_path / "a.json", failed=False)
    b = _write_manifest(tmp_path / "b.json", failed=True)

    rc = main(["compare-runs", str(a), str(b)])

    assert rc == 1


@pytest.mark.unit
def test_compare_runs_returns_1_on_unreadable_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write_manifest(tmp_path / "a.json")
    missing = tmp_path / "missing.json"

    rc = main(["compare-runs", str(a), str(missing)])

    assert rc == 1


@pytest.mark.unit
def test_compare_runs_accepts_run_dir_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a_dir = tmp_path / "a-run"
    b_dir = tmp_path / "b-run"
    a_dir.mkdir()
    b_dir.mkdir()
    _write_manifest(a_dir / "runpod_deploy_pull_manifest.json", gpu_id="H100")
    _write_manifest(b_dir / "runpod_deploy_pull_manifest.json", gpu_id="A100")

    rc = main(["compare-runs", str(a_dir), str(b_dir)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "H100  →  A100" in out
