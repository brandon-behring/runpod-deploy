from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from runpod_deploy.forensics import (
    EVENTS_FILENAME,
    MANIFEST_FILENAME,
    load_events,
    load_manifest,
    walk_run_dirs,
)


def _make_run_dir(parent: Path, ts: str, manifest: dict | None) -> Path:
    run_dir = parent / "artifacts" / "runpod" / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (run_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest))
    return run_dir


@pytest.mark.unit
def test_walk_run_dirs_returns_sorted_paths_with_manifest_only(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    later = _make_run_dir(project, "20260514T160000Z", {"job_name": "x"})
    earlier = _make_run_dir(project, "20260514T120000Z", {"job_name": "x"})
    _make_run_dir(project, "20260514T140000Z", manifest=None)  # no manifest → skipped

    found = walk_run_dirs(project)

    assert found == [earlier, later]


@pytest.mark.unit
def test_walk_run_dirs_returns_empty_when_no_artifacts_dir(tmp_path: Path) -> None:
    assert walk_run_dirs(tmp_path / "nonexistent") == []


@pytest.mark.unit
def test_load_manifest_accepts_run_dir_or_file_path(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, "ts", {"job_name": "demo", "schema_version": "v2"})

    via_dir = load_manifest(run_dir)
    via_file = load_manifest(run_dir / MANIFEST_FILENAME)

    assert via_dir == via_file
    assert via_dir is not None
    assert via_dir["job_name"] == "demo"


@pytest.mark.unit
def test_load_manifest_returns_none_on_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="runpod_deploy.forensics")
    result = load_manifest(tmp_path / "nope.json")
    assert result is None
    assert "manifest not found" in caplog.text


@pytest.mark.unit
def test_load_manifest_returns_none_on_bad_json(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = tmp_path / MANIFEST_FILENAME
    bad.write_text("{not valid json")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.forensics")

    result = load_manifest(bad)

    assert result is None
    assert "failed to parse" in caplog.text


@pytest.mark.unit
def test_load_manifest_returns_none_when_root_is_not_object(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = tmp_path / MANIFEST_FILENAME
    bad.write_text(json.dumps([1, 2, 3]))
    caplog.set_level(logging.WARNING, logger="runpod_deploy.forensics")

    result = load_manifest(bad)

    assert result is None
    assert "expected object" in caplog.text


@pytest.mark.unit
def test_load_events_parses_jsonl_skipping_blanks_and_garbage(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_dir = tmp_path / "ts"
    run_dir.mkdir()
    (run_dir / EVENTS_FILENAME).write_text(
        "\n"
        + json.dumps({"event": "gpu_selected", "gpu_id": "H100"})
        + "\n"
        + "{garbage line}\n"
        + "\n"
        + json.dumps({"event": "artifact_pull_completed", "label": "results"})
        + "\n"
    )
    caplog.set_level(logging.WARNING, logger="runpod_deploy.forensics")

    events = load_events(run_dir)

    assert [e["event"] for e in events] == ["gpu_selected", "artifact_pull_completed"]
    assert "malformed JSON" in caplog.text


@pytest.mark.unit
def test_load_events_returns_empty_when_file_missing(tmp_path: Path) -> None:
    assert load_events(tmp_path) == []
