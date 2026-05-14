from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections.abc import Iterable
from pathlib import Path

import pytest

from runpod_deploy.config import TelemetrySpec
from runpod_deploy.telemetry import TelemetrySession, start_session
from runpod_deploy.transport import RemoteRunner


def _runner(tmp_path: Path, *, dry_run: bool = False) -> RemoteRunner:
    return RemoteRunner(host="203.0.113.10", port=22, ssh_key=tmp_path / "key", dry_run=dry_run)


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=("ssh",), returncode=returncode, stdout=stdout, stderr=""
    )


def _patch_ssh_responses(monkeypatch: pytest.MonkeyPatch, responses: dict[str, str]) -> list[str]:
    """Patch RemoteRunner.ssh_exec to look up command -> stdout."""
    seen: list[str] = []

    def fake_ssh_exec(
        self: RemoteRunner, command: str, *, timeout_sec: int = 600, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        for key, out in responses.items():
            if key in command:
                return _completed(out)
        return _completed(stdout="", returncode=1)

    monkeypatch.setattr(RemoteRunner, "ssh_exec", fake_ssh_exec)
    return seen


def _patch_runpodctl(monkeypatch: pytest.MonkeyPatch, payload: object | None) -> None:
    """Patch subprocess.run inside telemetry to return JSON-serializable payload."""

    def fake_run(argv: Iterable[str], **_: object) -> subprocess.CompletedProcess[str]:
        if payload is None:
            return subprocess.CompletedProcess(
                args=tuple(argv), returncode=1, stdout="", stderr="boom"
            )
        return subprocess.CompletedProcess(
            args=tuple(argv), returncode=0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr("runpod_deploy.telemetry.subprocess.run", fake_run)


@pytest.mark.unit
def test_capture_start_writes_all_one_shot_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    _patch_ssh_responses(
        monkeypatch,
        {
            "nvidia-smi": "stub nvidia-smi output",
            "uname -a": "Linux pod-host x86_64",
            "python --version": "Python 3.13.0",
            "pip freeze": "torch==2.4.0\ntransformers==4.40.0",
        },
    )
    _patch_runpodctl(monkeypatch, {"costPerHr": 4.18, "desiredStatus": "RUNNING"})
    sess = start_session(
        run_dir=run_dir,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(),
        pod_id="abc123",
        assumed_hourly_rate_usd=1.65,
    )

    sess.capture_start()

    expected = {
        "nvidia_smi_start.txt",
        "pod_describe_start.json",
        "remote_env.json",
        "pip_freeze.txt",
    }
    assert {p.name for p in sess.files_written} == expected
    assert (run_dir / "nvidia_smi_start.txt").read_text() == "stub nvidia-smi output"
    env = json.loads((run_dir / "remote_env.json").read_text())
    assert env["remote_python_version"] == "Python 3.13.0"
    assert env["remote_uname"] == "Linux pod-host x86_64"


@pytest.mark.unit
def test_capture_start_extracts_cost_per_hr_from_pod_describe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_ssh_responses(monkeypatch, {})
    _patch_runpodctl(monkeypatch, {"costPerHr": 2.79, "desiredStatus": "RUNNING"})
    sess = start_session(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(capture_nvidia_smi=False, capture_remote_env=False),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )

    sess.capture_start()

    assert sess.gpu_price_per_hour_usd == 2.79
    assert sess.gpu_price_source == "pod_describe"


@pytest.mark.unit
def test_capture_start_falls_back_to_assumed_rate_when_cost_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_ssh_responses(monkeypatch, {})
    _patch_runpodctl(monkeypatch, {"id": "x", "desiredStatus": "RUNNING"})
    sess = start_session(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(capture_nvidia_smi=False, capture_remote_env=False),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )
    caplog.set_level(logging.WARNING, logger="runpod_deploy.telemetry")

    sess.capture_start()

    assert sess.gpu_price_per_hour_usd == 1.65
    assert sess.gpu_price_source == "assumed_rate"
    assert "costPerHr missing" in caplog.text


@pytest.mark.unit
def test_capture_end_emits_pod_killed_unexpected_for_terminated_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_ssh_responses(monkeypatch, {"nvidia-smi": "smi-end", "dmesg": "kernel boot ok"})
    _patch_runpodctl(monkeypatch, {"desiredStatus": "TERMINATED", "id": "x"})
    sess = start_session(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )

    sess.capture_end()

    assert sess.pod_final_state == "TERMINATED"
    events_path = tmp_path / "events.jsonl"
    assert events_path.exists()
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    kill_events = [e for e in events if e["event"] == "pod_killed_unexpected"]
    assert len(kill_events) == 1
    assert kill_events[0]["state"] == "TERMINATED"


@pytest.mark.unit
def test_capture_end_quiet_for_healthy_running_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_ssh_responses(monkeypatch, {"nvidia-smi": "x", "dmesg": "x"})
    _patch_runpodctl(monkeypatch, {"desiredStatus": "EXITED", "id": "x"})
    sess = start_session(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )

    sess.capture_end()

    assert sess.pod_final_state == "EXITED"
    assert not (tmp_path / "events.jsonl").exists()


@pytest.mark.unit
def test_emit_event_appends_jsonl(tmp_path: Path) -> None:
    sess = start_session(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )

    sess.emit_event("gpu_selected", gpu_id="g1", datacenter_id="dc1")
    sess.emit_event("datacenter_failover", **{"from": "dc0", "to": "dc1"})

    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "gpu_selected"
    assert first["gpu_id"] == "g1"
    assert "ts_utc" in first


@pytest.mark.unit
def test_dry_run_skips_all_capture_and_sampling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _patch_ssh_responses(monkeypatch, {"nvidia-smi": "x", "uname -a": "x"})
    _patch_runpodctl(monkeypatch, {"costPerHr": 9.99, "desiredStatus": "RUNNING"})
    sess = start_session(
        run_dir=tmp_path,
        runner=_runner(tmp_path, dry_run=True),
        spec=TelemetrySpec(),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
        dry_run=True,
    )

    sess.capture_start()
    sess.start_sampling()
    sess.stop_sampling()
    sess.capture_end()
    sess.emit_event("noop")

    assert seen == []
    assert sess.files_written == []
    assert sess.gpu_price_per_hour_usd is None


@pytest.mark.unit
def test_sampling_loop_writes_metrics_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ssh_responses(
        monkeypatch,
        {
            "nvidia-smi --query-gpu": "94, 38912, 40960, 72, 0",
            "top -b -n1": (
                "top - 12:00:00 up 1 day, load average: 7.21, 4.03, 3.10\n"
                "Tasks: 100 total\n"
                "%Cpu(s): 82.4 us,  3.1 sy,  0.0 ni\n"
            ),
            "free -m": "31204 65536",
            "df -B1 /workspace": "41234567890 214748364800",
        },
    )
    sess = TelemetrySession(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(sample_interval_sec=5),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )

    # Manually force a single sample without waiting the full interval:
    # call _sample_loop logic by setting interval low and tiny sleep.
    sess.start_sampling()
    # Wait for at least one sample by polling for the file.
    deadline = time.monotonic() + 8
    metrics = tmp_path / "metrics.jsonl"
    while time.monotonic() < deadline:
        if metrics.exists() and metrics.read_text().strip():
            break
        time.sleep(0.1)
    sess.stop_sampling()

    assert metrics.exists(), "sampler never wrote a row within 8s"
    lines = metrics.read_text().strip().splitlines()
    assert len(lines) >= 1
    row = json.loads(lines[0])
    assert row["gpu_util_pct"] == 94
    assert row["gpu_mem_used_mb"] == 38912
    assert row["host_mem_used_mb"] == 31204
    assert row["host_mem_total_mb"] == 65536
    assert row["workspace_disk_used_bytes"] == 41234567890
    assert row["cpu_load_1m"] == 7.21
    assert row["cpu_user_pct"] == 82.4
    assert row["cpu_sys_pct"] == 3.1


@pytest.mark.unit
def test_sampling_continues_when_one_ssh_call_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only nvidia-smi succeeds; top/free/df fail (returncode != 0)
    def fake_ssh_exec(
        self: RemoteRunner, command: str, *, timeout_sec: int = 600, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if "nvidia-smi --query-gpu" in command:
            return _completed("50, 100, 200, 60, 0")
        return _completed("", returncode=1)

    monkeypatch.setattr(RemoteRunner, "ssh_exec", fake_ssh_exec)
    sess = TelemetrySession(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(sample_interval_sec=5),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )

    sess.start_sampling()
    deadline = time.monotonic() + 8
    metrics = tmp_path / "metrics.jsonl"
    while time.monotonic() < deadline:
        if metrics.exists() and metrics.read_text().strip():
            break
        time.sleep(0.1)
    sess.stop_sampling()

    row = json.loads(metrics.read_text().strip().splitlines()[0])
    assert row["gpu_util_pct"] == 50
    # Failed samples should leave host/cpu/disk fields absent.
    assert "host_mem_used_mb" not in row
    assert "cpu_load_1m" not in row


@pytest.mark.unit
def test_stop_sampling_abandons_stuck_thread_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    block = threading.Event()

    def hanging_ssh(
        self: RemoteRunner, command: str, *, timeout_sec: int = 600, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        block.wait(timeout=60)  # never released by the test
        return _completed("")

    monkeypatch.setattr(RemoteRunner, "ssh_exec", hanging_ssh)
    monkeypatch.setattr("runpod_deploy.telemetry._JOIN_TIMEOUT_SEC", 0.5)

    sess = TelemetrySession(
        run_dir=tmp_path,
        runner=_runner(tmp_path),
        spec=TelemetrySpec(sample_interval_sec=5),
        pod_id="x",
        assumed_hourly_rate_usd=1.65,
    )
    caplog.set_level(logging.WARNING, logger="runpod_deploy.telemetry")
    sess.start_sampling()
    time.sleep(0.05)  # give the thread time to enter the SSH call
    sess.stop_sampling()

    # The hanging thread is abandoned; release it so it can exit cleanly.
    block.set()
    assert "did not exit" in caplog.text
