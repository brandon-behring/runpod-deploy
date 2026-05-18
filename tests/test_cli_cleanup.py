"""CLI tests for the cleanup-after-forensics surface.

Covers the three subcommands added in the 2026-05-17 pod-lifecycle fix:
- ``cleanup --state-file <path> --mode {preserve,stop,delete}``
- ``cleanup --all-stopped [--yes]``
- ``ls-stale``
- deprecated ``stop`` alias

The load-bearing assertion across these tests is that the CLI emits
``runpodctl pod delete`` argv whenever we expect a release-disk action,
which prevents the regression of the 2026-05-17 leak.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runpod_deploy.cli import main
from tests.conftest import FakeResult, FakeSubprocess


def _write_state_file(tmp_path: Path, pod_id: str = "pod-xyz") -> Path:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"pod_id": pod_id, "gpu_id": "A100"}))
    return state_file


@pytest.mark.unit
def test_cli_cleanup_single_pod_with_state_file_delete(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    state_file = _write_state_file(tmp_path)
    fake_subprocess.enqueue(FakeResult(returncode=0))

    rc = main(["cleanup", "--state-file", str(state_file), "--mode", "delete"])

    assert rc == 0
    assert fake_subprocess.calls == [["runpodctl", "pod", "delete", "pod-xyz"]]
    assert not state_file.exists()


@pytest.mark.unit
def test_cli_cleanup_single_pod_default_mode_is_delete(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    """Default --mode is `delete` — the operational fix for the leak."""
    state_file = _write_state_file(tmp_path)
    fake_subprocess.enqueue(FakeResult(returncode=0))

    rc = main(["cleanup", "--state-file", str(state_file)])

    assert rc == 0
    assert fake_subprocess.calls == [["runpodctl", "pod", "delete", "pod-xyz"]]


@pytest.mark.unit
def test_cli_cleanup_single_pod_mode_stop_preserves_state(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    state_file = _write_state_file(tmp_path)
    fake_subprocess.enqueue(FakeResult(returncode=0))

    rc = main(["cleanup", "--state-file", str(state_file), "--mode", "stop"])

    assert rc == 0
    assert fake_subprocess.calls == [["runpodctl", "pod", "stop", "pod-xyz"]]
    assert state_file.exists()


@pytest.mark.unit
def test_cli_cleanup_state_file_and_all_stopped_mutually_exclusive(
    tmp_path: Path,
) -> None:
    state_file = _write_state_file(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main(["cleanup", "--state-file", str(state_file), "--all-stopped"])
    assert excinfo.value.code == 2


@pytest.mark.unit
def test_cli_cleanup_all_stopped_yes_deletes_inventory(
    fake_subprocess: FakeSubprocess,
) -> None:
    """`cleanup --all-stopped --yes` deletes every EXITED pod without prompt."""
    inventory = json.dumps(
        [
            {"id": "pod-a", "name": "smoke-old", "volumeInGb": 50, "uptimeSeconds": None},
            {"id": "pod-b", "name": "bench-old", "volumeInGb": 100, "uptimeSeconds": None},
        ]
    )
    fake_subprocess.enqueue(FakeResult(returncode=0, stdout=inventory))
    fake_subprocess.enqueue(FakeResult(returncode=0))  # delete pod-a
    fake_subprocess.enqueue(FakeResult(returncode=0))  # delete pod-b

    rc = main(["cleanup", "--all-stopped", "--yes"])

    assert rc == 0
    argvs = [c[:4] for c in fake_subprocess.calls]
    list_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "list"]]
    assert len(list_calls) == 1
    assert "--status" in list_calls[0] and "EXITED" in list_calls[0]
    assert ["runpodctl", "pod", "delete", "pod-a"] in argvs
    assert ["runpodctl", "pod", "delete", "pod-b"] in argvs


@pytest.mark.unit
def test_cli_cleanup_all_stopped_empty_inventory_is_noop(
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.enqueue(FakeResult(returncode=0, stdout="[]"))

    rc = main(["cleanup", "--all-stopped", "--yes"])

    assert rc == 0
    delete_calls = [c for c in fake_subprocess.calls if c[:3] == ["runpodctl", "pod", "delete"]]
    assert delete_calls == []


@pytest.mark.unit
def test_cli_ls_stale_prints_inventory_with_total_cost_footer(
    fake_subprocess: FakeSubprocess,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = json.dumps(
        [
            {"id": "pod-a", "name": "smoke", "volumeInGb": 50, "uptimeSeconds": None},
            {"id": "pod-b", "name": "bench", "volumeInGb": 100, "uptimeSeconds": None},
            {"id": "pod-c", "name": "demo", "volumeInGb": 30, "uptimeSeconds": None},
        ]
    )
    fake_subprocess.enqueue(FakeResult(returncode=0, stdout=inventory))

    rc = main(["ls-stale"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "pod-a" in out and "pod-b" in out and "pod-c" in out
    # Total: (50+100+30) GB * 0.10/30 = 0.60/day, 18.00/mo
    assert "3 pods" in out
    assert "$0.60/day" in out


@pytest.mark.unit
def test_cli_ls_stale_json_output(
    fake_subprocess: FakeSubprocess,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = json.dumps([{"id": "pod-a", "name": "x", "volumeInGb": 50, "uptimeSeconds": None}])
    fake_subprocess.enqueue(FakeResult(returncode=0, stdout=inventory))

    rc = main(["ls-stale", "--json"])

    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert len(parsed) == 1
    assert parsed[0]["pod_id"] == "pod-a"
    assert parsed[0]["volume_in_gb"] == 50
    assert parsed[0]["estimated_daily_cost_usd"] == pytest.approx(50 * 0.10 / 30, abs=0.001)


@pytest.mark.unit
def test_cli_ls_stale_empty_inventory_prints_friendly_message(
    fake_subprocess: FakeSubprocess,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_subprocess.enqueue(FakeResult(returncode=0, stdout="[]"))

    rc = main(["ls-stale"])

    assert rc == 0
    assert "No stale" in capsys.readouterr().out


@pytest.mark.unit
def test_cli_stop_subcommand_no_longer_registered(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The legacy `runpod-deploy stop` subcommand was removed in v0.8.3.

    argparse rejects it as an unknown subcommand with exit code 2.
    """
    state_file = _write_state_file(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        main(["stop", "--state-file", str(state_file)])
    assert exc_info.value.code == 2
    assert "invalid choice: 'stop'" in capsys.readouterr().err
