from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from runpod_deploy.cli import main


def _events_file(run_dir: Path, events: list[dict]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


@pytest.mark.unit
def test_events_renders_timeline_with_offsets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _events_file(
        tmp_path,
        [
            {
                "ts_utc": "2026-05-14T12:00:00",
                "event": "gpu_selected",
                "gpu_id": "H100",
                "datacenter_id": "US-GA-2",
            },
            {
                "ts_utc": "2026-05-14T12:00:42",
                "event": "datacenter_failover",
                "from": "EUR-NO-2",
                "to": "US-GA-2",
                "reason": "no GPU available",
            },
            {
                "ts_utc": "2026-05-14T12:30:14",
                "event": "remote_step_completed",
                "name": "train",
            },
        ],
    )

    rc = main(["events", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[+0:00] gpu_selected" in out
    assert "gpu_id=H100" in out
    assert "[+0:42] datacenter_failover" in out
    # Quoted because contains space
    assert 'reason="no GPU available"' in out
    # 30 min, 14 sec → "[+30:14]"
    assert "[+30:14] remote_step_completed name=train" in out


@pytest.mark.unit
def test_events_handles_long_offset_with_hours(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _events_file(
        tmp_path,
        [
            {"ts_utc": "2026-05-14T12:00:00", "event": "first"},
            {"ts_utc": "2026-05-14T15:30:01", "event": "much_later"},
        ],
    )

    main(["events", str(tmp_path)])
    out = capsys.readouterr().out

    assert "[+3:30:01] much_later" in out


@pytest.mark.unit
def test_events_logs_info_when_jsonl_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "events.jsonl").write_text("")  # empty file
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["events", str(tmp_path)])

    assert rc == 0
    assert "no events" in caplog.text


@pytest.mark.unit
def test_events_raises_on_missing_run_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run-dir not found"):
        main(["events", str(tmp_path / "nonexistent")])


@pytest.mark.unit
def test_events_handles_missing_ts_utc_gracefully(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _events_file(
        tmp_path,
        [
            {"event": "no_timestamp", "label": "x"},
            {
                "ts_utc": "2026-05-14T12:00:00",
                "event": "first_with_ts",
            },
            {"ts_utc": "2026-05-14T12:01:00", "event": "second_with_ts"},
        ],
    )

    main(["events", str(tmp_path)])
    out = capsys.readouterr().out

    # First event without ts_utc shows the placeholder offset.
    assert "[+--:--] no_timestamp label=x" in out
    # Anchor is the FIRST event with a ts; later events compute offsets from it.
    assert "[+0:00] first_with_ts" in out
    assert "[+1:00] second_with_ts" in out
