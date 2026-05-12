"""SSH and rsync transport primitives."""

from __future__ import annotations

import contextlib
import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["RemoteRunError", "RemoteRunner", "RsyncTransfer", "log_cmd", "rsync_argv"]

logger = logging.getLogger(__name__)


class RemoteRunError(RuntimeError):
    """Raised when remote execution or remote-log monitoring fails."""


@dataclass(frozen=True, slots=True)
class RsyncTransfer:
    """Rendered rsync transfer."""

    label: str
    source: str
    destination: str
    excludes: tuple[str, ...] = ()
    delete: bool = True


@dataclass(frozen=True, slots=True)
class RemoteRunner:
    """Targets one SSH-ready pod."""

    host: str
    port: int
    ssh_key: Path
    dry_run: bool = False

    @property
    def target(self) -> str:
        """SSH user/host target. Direct TCP pods are root-owned."""
        return self.host if "@" in self.host else f"root@{self.host}"

    def ssh_argv(self, command: str, *, detached: bool = False) -> list[str]:
        """Build the ssh argv for attached or detached execution."""
        argv = [
            "ssh",
            "-p",
            str(self.port),
            "-i",
            str(self.ssh_key),
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=6",
        ]
        if detached:
            argv.extend(["-f", "-n", "-T"])
        else:
            argv.append("-T")
        argv.extend([self.target, command])
        return argv

    def ssh_exec(
        self,
        command: str,
        *,
        timeout_sec: int = 600,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run one remote command."""
        if not command:
            raise ValueError("command must be non-empty")
        argv = self.ssh_argv(command)
        log_cmd(logger, "ssh", argv)
        if self.dry_run:
            return subprocess.CompletedProcess(argv, 0, "", "")
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_sec, check=False
        )
        if check and result.returncode != 0:
            raise RemoteRunError(
                f"ssh command failed with exit {result.returncode}: {command}\n"
                f"stdout={result.stdout[-1000:]}\nstderr={result.stderr[-1000:]}"
            )
        return result

    def ssh_exec_detached(self, command: str, *, timeout_sec: int = 30) -> None:
        """Launch one remote command via `ssh -f -n -T`."""
        if not command:
            raise ValueError("command must be non-empty")
        argv = self.ssh_argv(command, detached=True)
        log_cmd(logger, "ssh-detached", argv)
        if self.dry_run:
            return
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            returncode = proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
            raise
        if returncode != 0:
            stderr_text = ""
            if proc.stderr is not None:
                stderr_text = proc.stderr.read()
            raise RemoteRunError(
                f"detached ssh exited {returncode}: {command}\nstderr={stderr_text[-1000:]}"
            )
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()

    def rsync_push(self, transfer: RsyncTransfer, *, timeout_sec: int = 3600) -> None:
        """Push a local path to the pod."""
        argv = rsync_argv(
            source=transfer.source,
            destination=f"{self.target}:{transfer.destination}",
            port=self.port,
            ssh_key=self.ssh_key,
            excludes=transfer.excludes,
            delete=transfer.delete,
        )
        log_cmd(logger, f"rsync-push:{transfer.label}", argv)
        if self.dry_run:
            return
        subprocess.run(argv, check=True, timeout=timeout_sec)

    def rsync_pull(
        self,
        *,
        remote_path: str,
        local_path: Path,
        excludes: tuple[str, ...] = (),
        timeout_sec: int = 1800,
        delete: bool = True,
    ) -> None:
        """Pull a remote path from the pod."""
        argv = rsync_argv(
            source=f"{self.target}:{remote_path}",
            destination=str(local_path),
            port=self.port,
            ssh_key=self.ssh_key,
            excludes=excludes,
            delete=delete,
        )
        log_cmd(logger, "rsync-pull", argv)
        if self.dry_run:
            return
        local_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(argv, check=True, timeout=timeout_sec)


def rsync_argv(
    *,
    source: str,
    destination: str,
    port: int,
    ssh_key: Path,
    excludes: tuple[str, ...],
    delete: bool = True,
) -> list[str]:
    """Build the project-standard rsync argv."""
    argv = [
        "rsync",
        "-az",
        "--no-owner",
        "--no-group",
        "--no-perms",
        "--omit-dir-times",
        "-e",
        f"ssh -p {port} -i {shlex.quote(str(ssh_key))} -o StrictHostKeyChecking=accept-new",
    ]
    if delete:
        argv.insert(6, "--delete")
    for pattern in excludes:
        argv.extend(["--exclude", pattern])
    argv.extend([source, destination])
    return argv


def log_cmd(target: logging.Logger, label: str, argv: list[Any]) -> None:
    """Emit a shell-readable argv at INFO on the given logger."""
    rendered = " ".join(shlex.quote(str(part)) for part in argv)
    target.info(f"$ [{label}] {rendered}")
