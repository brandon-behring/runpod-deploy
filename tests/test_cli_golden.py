"""Golden-file CLI snapshot tests (v0.7 PR-Q).

For each tested CLI subcommand: invoke with a deterministic fixture,
capture stdout, normalize tmp-path placeholders, and compare against
a checked-in `tests/fixtures/golden/*.txt` file.

Locks the UX contract — accidental output-format drift surfaces as a
diff against the golden. When the format *intentionally* changes,
regenerate:

    pytest tests/test_cli_golden.py --update-goldens
    git diff tests/fixtures/golden/   # eyeball
    git add tests/fixtures/golden/*.txt

Each golden is small (~10–30 lines), diff-friendly for PR review.

Path-normalization: tmp_path is replaced with `<TMP>` in captured
output so goldens don't bake in absolute paths from CI/host machines.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from runpod_deploy.cli import main

_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"


def _normalize(text: str, tmp_path: Path) -> str:
    """Replace tmp_path with `<TMP>` and any 20260515T... timestamp leaf with `<TS>`."""
    out = text.replace(str(tmp_path), "<TMP>")
    out = re.sub(r"\d{8}T\d{6}Z", "<TS>", out)
    return out


def _assert_or_update_golden(actual: str, golden_name: str, *, update: bool) -> None:
    """Either write the golden file or assert actual matches the saved one."""
    golden_path = _GOLDEN_DIR / golden_name
    if update:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual)
        return
    if not golden_path.exists():
        raise AssertionError(
            f"golden file missing: {golden_path}\n"
            f"Regenerate via: pytest {Path(__file__).relative_to(Path.cwd())} "
            f"--update-goldens"
        )
    expected = golden_path.read_text()
    if actual != expected:
        raise AssertionError(
            f"golden-file mismatch for {golden_name}.\n"
            f"--- expected ({golden_path}) ---\n{expected}\n"
            f"--- actual ---\n{actual}\n"
            f"If this change is intentional, regenerate with --update-goldens "
            f"and review the diff before committing."
        )


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def _stable_manifest() -> dict[str, object]:
    """Deterministic v2 manifest for goldens."""
    return {
        "schema_version": "v2",
        "job_name": "demo",
        "run_id": "demo-20260515T120000Z",
        "failed": False,
        "pod_id": "pod-abc",
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
            "local_git_sha": "abcd1234",
            "local_git_dirty": False,
            "payload_lockfile": "uv.lock",
        },
        "artifacts": [
            {
                "label": "results",
                "status": "success",
                "duration_sec": 3.2,
                "bytes_transferred": 1024,
            },
        ],
        "telemetry_files": ["nvidia_smi_start.txt", "events.jsonl"],
    }


def _stable_events_for_run(seed: int) -> list[dict[str, object]]:
    """Deterministic events.jsonl rows anchored at 2026-05-15T12:00:00Z."""
    base = "2026-05-15T12:00:00+00:00"
    return [
        {"ts_utc": base, "event": "gpu_selected", "gpu_id": "H100", "datacenter_id": "US-GA-2"},
        {
            "ts_utc": "2026-05-15T12:00:30+00:00",
            "event": "artifact_pull_completed",
            "label": "results",
            "duration_sec": 3.2,
        },
    ]


# ---- G1: manifest-summary (single file) ----


@pytest.mark.golden
def test_golden_manifest_summary_single(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update_goldens: bool,
) -> None:
    """G1: single-file `manifest-summary` output is stable."""
    manifest_path = tmp_path / "m.json"
    _write_manifest(manifest_path, _stable_manifest())
    rc = main(["manifest-summary", str(manifest_path)])
    assert rc == 0
    actual = _normalize(capsys.readouterr().out, tmp_path)
    _assert_or_update_golden(actual, "manifest_summary_single.txt", update=update_goldens)


# ---- G2: manifest-summary --root ----


@pytest.mark.golden
def test_golden_manifest_summary_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update_goldens: bool,
) -> None:
    """G2: `manifest-summary --root` aggregated output (TOTALS footer)."""
    root = tmp_path / "artifacts" / "runpod"
    # Two manifests with stable run_ids so the goldens don't change.
    _write_manifest(
        root / "20260515T120000Z" / "runpod_deploy_pull_manifest.json",
        {
            **_stable_manifest(),
            "run_id": "demo-a",
            "wall_time_sec": 1000.0,
            "estimated_cost_usd": 2.0,
        },
    )
    _write_manifest(
        root / "20260515T130000Z" / "runpod_deploy_pull_manifest.json",
        {
            **_stable_manifest(),
            "run_id": "demo-b",
            "wall_time_sec": 500.0,
            "estimated_cost_usd": 1.5,
            "failed": True,
        },
    )
    rc = main(["manifest-summary", "--root", str(root)])
    assert rc == 0
    actual = _normalize(capsys.readouterr().out, tmp_path)
    _assert_or_update_golden(actual, "manifest_summary_root.txt", update=update_goldens)


# ---- G3: events-query default table ----


@pytest.mark.golden
def test_golden_events_query_default_table(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update_goldens: bool,
) -> None:
    """G3: `events-query` default human-readable table."""
    root = tmp_path / "runpod"
    run_dir = root / "20260515T120000Z"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _stable_events_for_run(42)) + "\n"
    )
    # No --since, no --filter, no --json — exercises the default path.
    rc = main(["events-query", "--root", str(root)])
    assert rc == 0
    actual = _normalize(capsys.readouterr().out, tmp_path)
    _assert_or_update_golden(actual, "events_query_default_table.txt", update=update_goldens)


# ---- G4: events-query --json ----


@pytest.mark.golden
def test_golden_events_query_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update_goldens: bool,
) -> None:
    """G4: `events-query --json` JSONL output (run_dir field added)."""
    root = tmp_path / "runpod"
    run_dir = root / "20260515T120000Z"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _stable_events_for_run(42)) + "\n"
    )
    rc = main(["events-query", "--root", str(root), "--json"])
    assert rc == 0
    actual = _normalize(capsys.readouterr().out, tmp_path)
    _assert_or_update_golden(actual, "events_query_json.txt", update=update_goldens)


# ---- G5: ls-runs ----


@pytest.mark.golden
def test_golden_ls_runs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update_goldens: bool,
) -> None:
    """G5: `ls-runs` table output (existing v0.3.0 UX)."""
    root = tmp_path
    # ls-runs walks <project_root>/artifacts/runpod/<ts>/<manifest>.
    _write_manifest(
        root / "artifacts" / "runpod" / "20260515T120000Z" / "runpod_deploy_pull_manifest.json",
        {**_stable_manifest(), "run_id": "demo-a"},
    )
    _write_manifest(
        root / "artifacts" / "runpod" / "20260515T130000Z" / "runpod_deploy_pull_manifest.json",
        {**_stable_manifest(), "run_id": "demo-b", "failed": True, "estimated_cost_usd": 5.5},
    )
    rc = main(["ls-runs", "--project-root", str(root)])
    assert rc == 0
    actual = _normalize(capsys.readouterr().out, tmp_path)
    _assert_or_update_golden(actual, "ls_runs.txt", update=update_goldens)


# ---- G6: compare-runs ----


@pytest.mark.golden
def test_golden_compare_runs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update_goldens: bool,
) -> None:
    """G6: `compare-runs` diff output (locks the v0.3.0 format)."""
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    a = {**_stable_manifest(), "run_id": "demo-a", "gpu_id": "NVIDIA H100 80GB HBM3"}
    b = {
        **_stable_manifest(),
        "run_id": "demo-b",
        "gpu_id": "NVIDIA A100-SXM4-80GB",
        "wall_time_sec": 2500.0,
        "estimated_cost_usd": 3.5,
    }
    a_path.write_text(json.dumps(a))
    b_path.write_text(json.dumps(b))
    main(["compare-runs", str(a_path), str(b_path)])
    actual = _normalize(capsys.readouterr().out, tmp_path)
    _assert_or_update_golden(actual, "compare_runs.txt", update=update_goldens)


# ---- G7: events single-run timeline ----


@pytest.mark.golden
def test_golden_events_single_run_timeline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    update_goldens: bool,
) -> None:
    """G7: `events <run-dir>` wall-clock timeline output."""
    run_dir = tmp_path / "20260515T120000Z"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _stable_events_for_run(42)) + "\n"
    )
    rc = main(["events", str(run_dir)])
    assert rc == 0
    actual = _normalize(capsys.readouterr().out, tmp_path)
    _assert_or_update_golden(actual, "events_timeline.txt", update=update_goldens)
