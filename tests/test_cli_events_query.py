"""Tests for the `events-query` subcommand (issue #20).

Covers:
- Aggregation across run dirs under --root (rglob walk for events.jsonl).
- --filter KEY=VALUE exact-match predicates with AND semantics.
- --since DURATION wall-clock window (s/m/h/d unit parsing).
- --json opt-in JSONL output vs default human-readable table.
- Helper validation: _parse_duration, _parse_filter_arg.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runpod_deploy.cli import _parse_duration, _parse_filter_arg, main


def _write_events(run_dir: Path, events: list[dict[str, object]]) -> None:
    """Drop `events.jsonl` into run_dir with the given JSONL rows."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _ts_recent(seconds_ago: int = 0) -> str:
    """ISO-formatted UTC timestamp `seconds_ago` seconds in the past."""
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def _ts_old() -> str:
    """A clearly-old timestamp (8 days ago) for --since tests."""
    return (datetime.now(UTC) - timedelta(days=8)).isoformat()


# ---- _parse_duration ----


@pytest.mark.unit
def test_parse_duration_seconds() -> None:
    assert _parse_duration("30s") == 30


@pytest.mark.unit
def test_parse_duration_minutes() -> None:
    assert _parse_duration("5m") == 300


@pytest.mark.unit
def test_parse_duration_hours() -> None:
    assert _parse_duration("1h") == 3600


@pytest.mark.unit
def test_parse_duration_days() -> None:
    assert _parse_duration("7d") == 604800


@pytest.mark.unit
def test_parse_duration_rejects_missing_unit() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="N \\+ unit"):
        _parse_duration("3600")


@pytest.mark.unit
def test_parse_duration_rejects_invalid_unit() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="N \\+ unit"):
        _parse_duration("1y")


@pytest.mark.unit
def test_parse_duration_rejects_decimal() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_duration("1.5h")


@pytest.mark.unit
def test_parse_duration_rejects_compound() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_duration("1h30m")


# ---- _parse_filter_arg ----


@pytest.mark.unit
def test_parse_filter_arg_happy_path() -> None:
    assert _parse_filter_arg("event=pod_killed_unexpected") == (
        "event",
        "pod_killed_unexpected",
    )


@pytest.mark.unit
def test_parse_filter_arg_value_may_contain_equals() -> None:
    assert _parse_filter_arg("url=https://x.y?a=b") == ("url", "https://x.y?a=b")


@pytest.mark.unit
def test_parse_filter_arg_rejects_missing_equals() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="KEY=VALUE"):
        _parse_filter_arg("noequals")


@pytest.mark.unit
def test_parse_filter_arg_rejects_invalid_key() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="valid identifier"):
        _parse_filter_arg("my-key=value")


# ---- end-to-end events-query ----


@pytest.mark.unit
def test_events_query_no_filters_emits_all_events_as_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default (no filters, no --json) emits all events under --root as a table."""
    root = tmp_path / "runpod"
    _write_events(
        root / "20260515T000000Z",
        [
            {"ts_utc": _ts_recent(60), "event": "gpu_selected", "gpu_id": "RTX 4090"},
            {"ts_utc": _ts_recent(30), "event": "artifact_pull_completed", "label": "preds"},
        ],
    )
    rc = main(["events-query", "--root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "gpu_selected" in out
    assert "artifact_pull_completed" in out
    assert "20260515T000000Z" in out  # run_dir leaf appears in each line
    assert "RTX 4090" in out


@pytest.mark.unit
def test_events_query_filter_event_field_keeps_only_matching(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--filter event=NAME filters to exact-match event-name rows only."""
    root = tmp_path / "runpod"
    _write_events(
        root / "20260515T000000Z",
        [
            {"ts_utc": _ts_recent(60), "event": "gpu_selected"},
            {"ts_utc": _ts_recent(30), "event": "pod_killed_unexpected"},
            {"ts_utc": _ts_recent(20), "event": "artifact_pull_completed"},
        ],
    )
    rc = main(["events-query", "--root", str(root), "--filter", "event=pod_killed_unexpected"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pod_killed_unexpected" in out
    assert "gpu_selected" not in out
    assert "artifact_pull_completed" not in out


@pytest.mark.unit
def test_events_query_multiple_filters_and_together(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two --filter args AND together."""
    root = tmp_path / "runpod"
    _write_events(
        root / "20260515T000000Z",
        [
            # Matches only event=gpu_selected: matches event filter, dc doesn't
            {"ts_utc": _ts_recent(60), "event": "gpu_selected", "datacenter_id": "US-MD-1"},
            # Matches both
            {"ts_utc": _ts_recent(40), "event": "gpu_selected", "datacenter_id": "EU-RO-1"},
            # Wrong event
            {
                "ts_utc": _ts_recent(20),
                "event": "pod_killed_unexpected",
                "datacenter_id": "EU-RO-1",
            },
        ],
    )
    rc = main(
        [
            "events-query",
            "--root",
            str(root),
            "--filter",
            "event=gpu_selected",
            "--filter",
            "datacenter_id=EU-RO-1",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    # Exactly one matching row: gpu_selected + EU-RO-1
    matching = [line for line in out.splitlines() if "gpu_selected" in line]
    assert len(matching) == 1
    assert "EU-RO-1" in matching[0]
    assert "US-MD-1" not in matching[0]


@pytest.mark.unit
def test_events_query_since_drops_old_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--since 1h drops events older than 1h."""
    root = tmp_path / "runpod"
    _write_events(
        root / "20260515T000000Z",
        [
            {"ts_utc": _ts_recent(60), "event": "recent_event"},  # ~1 min ago
            {"ts_utc": _ts_old(), "event": "ancient_event"},  # 8d ago
        ],
    )
    rc = main(["events-query", "--root", str(root), "--since", "1h"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "recent_event" in out
    assert "ancient_event" not in out


@pytest.mark.unit
def test_events_query_json_emits_jsonl_with_run_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--json emits one JSON object per event, with run_dir added."""
    root = tmp_path / "runpod"
    _write_events(
        root / "20260515T120000Z",
        [
            {"ts_utc": _ts_recent(30), "event": "gpu_selected", "gpu_id": "RTX 4090"},
        ],
    )
    rc = main(["events-query", "--root", str(root), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event"] == "gpu_selected"
    assert row["gpu_id"] == "RTX 4090"
    assert row["run_dir"] == "20260515T120000Z"


@pytest.mark.unit
def test_events_query_aggregates_across_multiple_run_dirs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """rglob walks deep into multiple run-dirs and concatenates results."""
    root = tmp_path / "runpod"
    _write_events(
        root / "20260514T000000Z",
        [{"ts_utc": _ts_recent(100), "event": "gpu_selected", "gpu_id": "A100"}],
    )
    _write_events(
        root / "20260515T000000Z",
        [{"ts_utc": _ts_recent(60), "event": "gpu_selected", "gpu_id": "H100"}],
    )
    rc = main(["events-query", "--root", str(root), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(rows) == 2
    run_dirs = {r["run_dir"] for r in rows}
    assert run_dirs == {"20260514T000000Z", "20260515T000000Z"}


@pytest.mark.unit
def test_events_query_missing_root_raises(tmp_path: Path) -> None:
    """A nonexistent --root path is a hard error (fail-fast policy)."""
    with pytest.raises(FileNotFoundError, match="--root directory not found"):
        main(["events-query", "--root", str(tmp_path / "nope")])


@pytest.mark.unit
def test_events_query_empty_root_info_logs_and_exits_zero(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Empty --root (no events.jsonl files) logs INFO + exits 0."""
    import logging as _logging

    root = tmp_path / "runpod"
    root.mkdir()
    caplog.set_level(_logging.INFO, logger="runpod_deploy")
    rc = main(["events-query", "--root", str(root)])
    assert rc == 0
    assert "no matching events" in caplog.text


@pytest.mark.unit
def test_events_query_no_matches_after_filter_info_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """All events filtered out → INFO log + exit 0 (not a failure)."""
    import logging as _logging

    root = tmp_path / "runpod"
    _write_events(
        root / "20260515T000000Z",
        [{"ts_utc": _ts_recent(60), "event": "gpu_selected"}],
    )
    caplog.set_level(_logging.INFO, logger="runpod_deploy")
    rc = main(["events-query", "--root", str(root), "--filter", "event=nonexistent"])
    assert rc == 0
    assert "no matching events" in caplog.text
