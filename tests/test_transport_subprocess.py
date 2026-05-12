from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from runpod_deploy.transport import RemoteRunError, RemoteRunner
from tests.conftest import FakeResult, FakeSubprocess


def _runner(tmp_path: Path, *, dry_run: bool = False) -> RemoteRunner:
    return RemoteRunner(
        host="1.2.3.4",
        port=22022,
        ssh_key=tmp_path / "id_ed25519",
        dry_run=dry_run,
    )


# ---------- ssh_exec ----------


@pytest.mark.unit
def test_ssh_exec_returns_completed_process_on_success(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    fake_subprocess.enqueue(FakeResult(returncode=0, stdout="ok"))

    result = _runner(tmp_path).ssh_exec("nvidia-smi")

    assert result.returncode == 0
    assert result.stdout == "ok"
    argv = fake_subprocess.calls[0]
    assert argv[:2] == ["ssh", "-p"]
    assert "22022" in argv
    assert "root@1.2.3.4" in argv
    assert "nvidia-smi" in argv


@pytest.mark.unit
def test_ssh_exec_raises_remote_run_error_on_nonzero(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    long_stderr = "x" * 2000
    fake_subprocess.enqueue(FakeResult(returncode=1, stderr=long_stderr))

    with pytest.raises(RemoteRunError) as exc_info:
        _runner(tmp_path).ssh_exec("nvidia-smi")

    message = str(exc_info.value)
    assert "exit 1" in message
    stderr_suffix = message.split("stderr=", 1)[1]
    assert stderr_suffix == "x" * 1000


@pytest.mark.unit
def test_ssh_exec_check_false_returns_failed_process(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    fake_subprocess.enqueue(FakeResult(returncode=1, stderr="nope"))

    result = _runner(tmp_path).ssh_exec("false", check=False)

    assert result.returncode == 1
    assert result.stderr == "nope"


@pytest.mark.unit
def test_ssh_exec_rejects_empty_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command must be non-empty"):
        _runner(tmp_path).ssh_exec("")


@pytest.mark.unit
def test_ssh_exec_dry_run_skips_subprocess(fake_subprocess: FakeSubprocess, tmp_path: Path) -> None:
    result = _runner(tmp_path, dry_run=True).ssh_exec("nvidia-smi")

    assert result.returncode == 0
    assert fake_subprocess.calls == []


# ---------- ssh_exec_detached ----------


@pytest.mark.unit
def test_ssh_exec_detached_invokes_popen_with_detached_flags(
    fake_popen: Any, tmp_path: Path
) -> None:
    instances = fake_popen(returncode_val=0)

    _runner(tmp_path).ssh_exec_detached("nohup bash run.sh &")

    assert len(instances) == 1
    argv = instances[0].argv
    assert "-f" in argv
    assert "-n" in argv
    assert "-T" in argv
    assert instances[0].waited is True


@pytest.mark.unit
def test_ssh_exec_detached_raises_on_nonzero_exit(fake_popen: Any, tmp_path: Path) -> None:
    fake_popen(returncode_val=2, stderr_text="boom")

    with pytest.raises(RemoteRunError, match="boom"):
        _runner(tmp_path).ssh_exec_detached("nohup bash run.sh &")


@pytest.mark.unit
def test_ssh_exec_detached_kills_on_timeout_expired(fake_popen: Any, tmp_path: Path) -> None:
    instances = fake_popen(timeout=True)

    with pytest.raises(subprocess.TimeoutExpired):
        _runner(tmp_path).ssh_exec_detached("nohup bash run.sh &")

    assert instances[0].killed is True


@pytest.mark.unit
def test_ssh_exec_detached_rejects_empty_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command must be non-empty"):
        _runner(tmp_path).ssh_exec_detached("")


@pytest.mark.unit
def test_ssh_exec_detached_dry_run_does_not_call_popen(fake_popen: Any, tmp_path: Path) -> None:
    instances = fake_popen(returncode_val=0)

    _runner(tmp_path, dry_run=True).ssh_exec_detached("nohup bash run.sh &")

    assert instances == []
