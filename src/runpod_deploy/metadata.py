"""Auto-captured deploy metadata (local git + payload lockfile)."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path

__all__ = ["capture_local_git", "capture_payload_lockfile"]

logger = logging.getLogger(__name__)

_LOCKFILE_CANDIDATES = ("uv.lock", "requirements.txt")


def capture_local_git(project_root: Path) -> dict[str, object]:
    """Capture local git SHA, dirty flag, and branch for ``project_root``.

    Returns a dict with keys ``local_git_sha``, ``local_git_dirty``,
    ``local_git_branch``. Each value is ``None`` and a WARNING is logged
    when ``project_root`` is not a git working tree, when git is not on
    PATH, or when the git invocation fails. Never raises.
    """
    null: dict[str, object] = {
        "local_git_sha": None,
        "local_git_dirty": None,
        "local_git_branch": None,
    }
    if not project_root.is_dir():
        logger.warning(f"[metadata] capture_local_git: {project_root} is not a directory")
        return null
    sha = _run_git(project_root, ("rev-parse", "HEAD"))
    if sha is None:
        return null
    branch = _run_git(project_root, ("rev-parse", "--abbrev-ref", "HEAD"))
    porcelain = _run_git(project_root, ("status", "--porcelain"))
    dirty = bool(porcelain) if porcelain is not None else None
    return {
        "local_git_sha": sha,
        "local_git_dirty": dirty,
        "local_git_branch": branch,
    }


def capture_payload_lockfile(project_root: Path) -> dict[str, object]:
    """Locate and hash the payload's lockfile under ``project_root``.

    Looks for ``uv.lock`` then ``requirements.txt`` (first match wins).
    Returns a dict with keys ``payload_lockfile`` (the basename or None)
    and ``payload_lockfile_sha256`` (hex digest or None). Logs a WARNING
    when neither file exists. Never raises.
    """
    null: dict[str, object] = {"payload_lockfile": None, "payload_lockfile_sha256": None}
    if not project_root.is_dir():
        logger.warning(f"[metadata] capture_payload_lockfile: {project_root} is not a directory")
        return null
    for name in _LOCKFILE_CANDIDATES:
        candidate = project_root / name
        if candidate.is_file():
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            return {"payload_lockfile": name, "payload_lockfile_sha256": digest}
    logger.warning(
        f"[metadata] capture_payload_lockfile: no lockfile under {project_root} "
        f"(tried {list(_LOCKFILE_CANDIDATES)})"
    )
    return null


def _run_git(project_root: Path, args: tuple[str, ...]) -> str | None:
    """Run a git subcommand under ``project_root``; return stripped stdout or None."""
    try:
        result = subprocess.run(
            ("git", "-C", str(project_root), *args),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError:
        logger.warning("[metadata] git not on PATH; skipping local git capture")
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"[metadata] git {' '.join(args)} timed out under {project_root}")
        return None
    if result.returncode != 0:
        logger.warning(
            f"[metadata] git {' '.join(args)} exited {result.returncode} "
            f"under {project_root}: {result.stderr.strip()!r}"
        )
        return None
    return result.stdout.strip()
