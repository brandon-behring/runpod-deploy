"""Shared test fixtures, primarily subprocess fakes for provider/transport tests."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeResult:
    """One enqueued subprocess.run response."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class FakeSubprocess:
    """Captures subprocess.run calls and serves FakeResults from a FIFO queue."""

    calls: list[list[str]] = field(default_factory=list)
    responses: list[FakeResult] = field(default_factory=list)

    def enqueue(self, *results: FakeResult) -> None:
        self.responses.extend(results)

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        result = self.responses.pop(0) if self.responses else FakeResult()
        return subprocess.CompletedProcess(argv, result.returncode, result.stdout, result.stderr)


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> FakeSubprocess:
    """Patch subprocess.run inside provider and transport module namespaces."""
    fake = FakeSubprocess()
    monkeypatch.setattr("runpod_deploy.provider.subprocess.run", fake)
    monkeypatch.setattr("runpod_deploy.transport.subprocess.run", fake)
    return fake


class _StringStream:
    """Minimal file-like supporting .read() and .close() for FakePopen pipes."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._closed = False

    def read(self) -> str:
        return self._text

    def close(self) -> None:
        self._closed = True


@dataclass
class FakePopen:
    """Replacement for subprocess.Popen used by ssh_exec_detached."""

    argv: list[str]
    returncode_val: int = 0
    stderr_text: str = ""
    timeout: bool = False
    killed: bool = False
    waited: bool = False
    stdin: _StringStream = field(init=False)
    stdout: _StringStream = field(init=False)
    stderr: _StringStream = field(init=False)

    def __post_init__(self) -> None:
        self.stdin = _StringStream("")
        self.stdout = _StringStream("")
        self.stderr = _StringStream(self.stderr_text)

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        if self.timeout:
            raise subprocess.TimeoutExpired(self.argv, timeout or 0)
        return self.returncode_val

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def fake_popen(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Factory fixture: call with desired behavior dict, returns list of FakePopen instances."""
    instances: list[FakePopen] = []

    def install(**behavior: Any) -> list[FakePopen]:
        def make(argv: list[str], **_kwargs: Any) -> FakePopen:
            inst = FakePopen(argv=list(argv), **behavior)
            instances.append(inst)
            return inst

        monkeypatch.setattr("runpod_deploy.transport.subprocess.Popen", make)
        return instances

    yield install
