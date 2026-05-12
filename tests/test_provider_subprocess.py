from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from runpod_deploy.config import build_job_context, load_job_spec
from runpod_deploy.provider import (
    PodConnection,
    provision_pod,
    run_json,
    stop_pod,
    wait_for_pod_ready,
)
from tests.conftest import FakeResult, FakeSubprocess


def _write_min_config(path: Path, *, state_file: Path) -> Path:
    path.write_text(f"""
schema_version: 1
name: demo
run_id_prefix: demo
state_file: {state_file}
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenter_id: EU-RO-1
  gpu_order:
    - NVIDIA RTX A4000
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
""")
    return path


# ---------- run_json ----------


@pytest.mark.unit
def test_run_json_returns_parsed_payload(fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.enqueue(FakeResult(stdout='{"id": "abc", "n": 7}'))

    payload = run_json(["runpodctl", "pod", "get", "abc", "-o", "json"])

    assert payload == {"id": "abc", "n": 7}
    assert fake_subprocess.calls[0][:2] == ["runpodctl", "pod"]


@pytest.mark.unit
def test_run_json_raises_on_nonzero_returncode(fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.enqueue(FakeResult(returncode=1, stderr="boom"))

    with pytest.raises(RuntimeError, match="stderr=boom"):
        run_json(["runpodctl", "pod", "get"])


@pytest.mark.unit
def test_run_json_raises_on_invalid_json(fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.enqueue(FakeResult(stdout="not json at all"))

    with pytest.raises(json.JSONDecodeError):
        run_json(["runpodctl", "pod", "get"])


# ---------- wait_for_pod_ready ----------


def _ssh_running_payload(host: str = "1.2.3.4", port: int = 22) -> str:
    return json.dumps({"desiredStatus": "RUNNING", "ssh": {"ip": host, "port": port}})


@pytest.fixture
def frozen_time(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """time.time returns successive values; time.sleep is a no-op."""
    ticks: list[float] = [1000.0]

    def fake_time() -> float:
        return ticks[-1]

    def fake_sleep(_seconds: float) -> None:
        ticks.append(ticks[-1] + 1.0)

    monkeypatch.setattr("runpod_deploy.provider.time.time", fake_time)
    monkeypatch.setattr("runpod_deploy.provider.time.sleep", fake_sleep)
    return ticks


@pytest.fixture
def job_ctx(tmp_path: Path) -> Path:
    """Build a minimal JobContext writable to a tmp state_file. Returns the config path."""
    state_file = tmp_path / "state.json"
    return _write_min_config(tmp_path / "job.yaml", state_file=state_file)


@pytest.mark.unit
def test_wait_for_pod_ready_returns_on_running_status(
    fake_subprocess: FakeSubprocess, frozen_time: list[float], job_ctx: Path
) -> None:
    fake_subprocess.enqueue(
        FakeResult(stdout=json.dumps({"desiredStatus": "STARTING"})),
        FakeResult(stdout=json.dumps({"desiredStatus": "STARTING"})),
        FakeResult(stdout=_ssh_running_payload(host="5.6.7.8", port=22033)),
    )
    ctx = build_job_context(load_job_spec(job_ctx), job_ctx)

    pod = wait_for_pod_ready("pod-xyz", ctx, gpu_id="NVIDIA RTX A4000")

    assert pod == PodConnection(
        pod_id="pod-xyz", host="5.6.7.8", port=22033, gpu_id="NVIDIA RTX A4000"
    )


@pytest.mark.unit
def test_wait_for_pod_ready_times_out(
    fake_subprocess: FakeSubprocess, monkeypatch: pytest.MonkeyPatch, job_ctx: Path
) -> None:
    times = iter([0.0, 999.0])

    def fake_time() -> float:
        return next(times, 999.0)

    monkeypatch.setattr("runpod_deploy.provider.time.time", fake_time)
    monkeypatch.setattr("runpod_deploy.provider.time.sleep", lambda _s: None)
    fake_subprocess.enqueue(FakeResult(stdout=json.dumps({"desiredStatus": "STARTING"})))
    ctx = build_job_context(load_job_spec(job_ctx), job_ctx)

    with pytest.raises(RuntimeError, match="did not become SSH-ready"):
        wait_for_pod_ready("pod-xyz", ctx, gpu_id="NVIDIA RTX A4000")


@pytest.mark.unit
def test_wait_for_pod_ready_tolerates_non_dict_payload(
    fake_subprocess: FakeSubprocess, frozen_time: list[float], job_ctx: Path
) -> None:
    fake_subprocess.enqueue(
        FakeResult(stdout="[]"),
        FakeResult(stdout=_ssh_running_payload()),
    )
    ctx = build_job_context(load_job_spec(job_ctx), job_ctx)

    pod = wait_for_pod_ready("pod-xyz", ctx, gpu_id="NVIDIA RTX A4000")

    assert pod.host == "1.2.3.4"


# ---------- provision_pod ----------


@pytest.mark.unit
def test_provision_pod_writes_state_file_and_returns_connection(
    fake_subprocess: FakeSubprocess, frozen_time: list[float], job_ctx: Path
) -> None:
    fake_subprocess.enqueue(
        FakeResult(stdout='{"id": "pod-xyz"}'),
        FakeResult(stdout=_ssh_running_payload(host="9.9.9.9", port=22044)),
    )
    ctx = build_job_context(load_job_spec(job_ctx), job_ctx)

    pod = provision_pod(ctx, volume_id=None, gpu_id="NVIDIA RTX A4000", dry_run=False)

    assert pod.pod_id == "pod-xyz"
    assert pod.host == "9.9.9.9"
    state = json.loads(ctx.spec.resolved_state_file.read_text())
    assert state == {"pod_id": "pod-xyz", "gpu_id": "NVIDIA RTX A4000"}


@pytest.mark.unit
def test_provision_pod_raises_when_create_fails(
    fake_subprocess: FakeSubprocess, job_ctx: Path
) -> None:
    fake_subprocess.enqueue(FakeResult(returncode=1, stderr="quota exceeded"))
    ctx = build_job_context(load_job_spec(job_ctx), job_ctx)

    with pytest.raises(RuntimeError, match="pod create failed"):
        provision_pod(ctx, volume_id=None, gpu_id="NVIDIA RTX A4000", dry_run=False)


@pytest.mark.unit
def test_provision_pod_raises_when_no_pod_id_returned(
    fake_subprocess: FakeSubprocess, job_ctx: Path
) -> None:
    fake_subprocess.enqueue(FakeResult(stdout="{}"))
    ctx = build_job_context(load_job_spec(job_ctx), job_ctx)

    with pytest.raises(RuntimeError, match="no pod id"):
        provision_pod(ctx, volume_id=None, gpu_id="NVIDIA RTX A4000", dry_run=False)


@pytest.mark.unit
def test_provision_pod_dry_run_returns_sentinel(
    fake_subprocess: FakeSubprocess, job_ctx: Path
) -> None:
    ctx = build_job_context(load_job_spec(job_ctx), job_ctx)

    pod = provision_pod(ctx, volume_id=None, gpu_id="NVIDIA RTX A4000", dry_run=True)

    assert pod.pod_id == "<pod-id>"
    assert pod.host == "203.0.113.10"
    assert pod.port == 22022
    assert fake_subprocess.calls == []


# ---------- stop_pod ----------


@pytest.mark.unit
def test_stop_pod_calls_runpodctl_and_deletes_state_file(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text("{}")
    fake_subprocess.enqueue(FakeResult(returncode=0))

    stop_pod("pod-xyz", dry_run=False, state_file=state_file)

    assert fake_subprocess.calls == [["runpodctl", "pod", "stop", "pod-xyz"]]
    assert not state_file.exists()


@pytest.mark.unit
def test_stop_pod_warns_but_does_not_raise_on_failure(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="runpod_deploy")
    state_file = tmp_path / "state.json"
    state_file.write_text("{}")
    fake_subprocess.enqueue(FakeResult(returncode=2, stderr="not found"))

    stop_pod("pod-xyz", dry_run=False, state_file=state_file)

    assert "[warn] failed to stop pod pod-xyz" in caplog.text
    assert state_file.exists()


@pytest.mark.unit
def test_stop_pod_skips_subprocess_for_sentinel_pod_id(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text("{}")

    stop_pod("<pod-id>", dry_run=False, state_file=state_file)

    assert fake_subprocess.calls == []
    assert state_file.exists()
