"""Read-only helpers for inspecting past run artifacts.

Used by the v0.3.0 forensic CLI subcommands (``ls-runs``, ``compare-runs``,
``events``) to walk ``artifacts/runpod/*/`` directories and parse the
v1/v2 ``runpod_deploy_pull_manifest.json`` and ``events.jsonl`` files
that ``orchestrator.run_job`` writes per run.

Pure helpers; no subprocess. All errors map to WARNING + ``None``/empty
returns so a corrupt run dir doesn't break the whole listing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

__all__ = [
    "load_events",
    "load_manifest",
    "walk_run_dirs",
]

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "runpod_deploy_pull_manifest.json"
EVENTS_FILENAME = "events.jsonl"


def walk_run_dirs(project_root: Path) -> list[Path]:
    """Return run-directory paths under ``<project_root>/artifacts/runpod/*``.

    A "run directory" is any subdirectory that contains a
    ``runpod_deploy_pull_manifest.json``. Returned paths are sorted
    lexicographically (which equals chronologically for the
    ``YYYYMMDDTHHMMSSZ`` directory names this repo emits).
    """
    base = project_root / "artifacts" / "runpod"
    if not base.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / MANIFEST_FILENAME).is_file():
            found.append(child)
    return found


def load_manifest(path: Path) -> dict[str, Any] | None:
    """Read and parse a manifest JSON. Returns None + WARNING on failure.

    Accepts either a path to the manifest file directly or a run-directory
    path (in which case the canonical filename is appended).
    """
    if path.is_dir():
        path = path / MANIFEST_FILENAME
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        logger.warning(f"[forensics] manifest not found: {path}")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[forensics] failed to parse {path}: {exc}")
        return None
    if not isinstance(raw, dict):
        logger.warning(f"[forensics] manifest at {path} is {type(raw).__name__}, expected object")
        return None
    return raw


def load_events(run_dir: Path) -> list[dict[str, Any]]:
    """Parse ``events.jsonl`` one line at a time. Skips malformed lines with WARNING."""
    path = run_dir / EVENTS_FILENAME if run_dir.is_dir() else run_dir
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text()
    except OSError as exc:
        logger.warning(f"[forensics] failed to read {path}: {exc}")
        return []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning(f"[forensics] {path}:{lineno} malformed JSON ({exc}); skipping")
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out
