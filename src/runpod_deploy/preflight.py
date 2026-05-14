"""Opt-in pre-run checks: GPU availability, consumer-pyproject scan, path scan."""

from __future__ import annotations

import difflib
import logging
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from runpod_deploy.config import JobContext
from runpod_deploy.provider import run_json

__all__ = [
    "check_gpu_availability",
    "fetch_datacenter_payload",
    "scan_consumer_pyproject",
    "scan_staged_payloads_for_absolute_paths",
]

logger = logging.getLogger(__name__)

_AVAILABLE_STOCK = {"high", "medium", "low"}
_UNAVAILABLE_STOCK = {"", "none", "unavailable", "out"}
_SCAN_EXTENSIONS = frozenset({".py", ".yaml", ".yml", ".toml", ".json", ".sh"})
_SCAN_MAX_BYTES = 1 * 1024 * 1024
_MATCHES_PER_FILE = 3
_ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"/Users/[^/\s'\"]+/"),
    re.compile(r"/home/[^/\s'\"]+/"),
    re.compile(r"C:\\\\Users\\\\"),
)


def fetch_datacenter_payload(datacenter_id: str) -> Mapping[str, Any]:
    """Fetch one datacenter entry from `runpodctl datacenter list -o json`.

    Raises RuntimeError if the datacenter id is not present.
    """
    payload = run_json(["runpodctl", "datacenter", "list", "-o", "json"])
    if not isinstance(payload, list):
        raise RuntimeError(
            f"runpodctl datacenter list returned {type(payload).__name__}, expected list"
        )
    for entry in payload:
        if isinstance(entry, dict) and entry.get("id") == datacenter_id:
            return entry
    observed = [str(e.get("id")) for e in payload if isinstance(e, dict)]
    raise RuntimeError(
        f"datacenter {datacenter_id!r} not found in runpodctl output; observed={observed}"
    )


def check_gpu_availability(ctx: JobContext) -> None:
    """Validate every gpu_order entry against live RunPod stock data."""
    spec = ctx.spec
    entry = fetch_datacenter_payload(spec.pod.datacenters[0])
    availability = entry.get("gpuAvailability") or []
    if not isinstance(availability, list):
        raise RuntimeError(
            f"datacenter {spec.pod.datacenters[0]!r} gpuAvailability is "
            f"{type(availability).__name__}, expected list"
        )
    by_id: dict[str, str] = {}
    for item in availability:
        if isinstance(item, dict):
            name = str(item.get("gpuId") or "")
            status = str(item.get("stockStatus") or "").strip()
            if name:
                by_id[name] = status
    known_names = list(by_id.keys())
    for gpu_id in spec.pod.gpu_order:
        if gpu_id not in by_id:
            suggestions = difflib.get_close_matches(gpu_id, known_names, n=1, cutoff=0.6)
            hint = f" — did you mean {suggestions[0]!r}?" if suggestions else ""
            logger.error(f"[gpu] {gpu_id!r} not in datacenter {spec.pod.datacenters[0]}{hint}")
            continue
        status = by_id[gpu_id]
        if status.lower() in _UNAVAILABLE_STOCK:
            logger.warning(f"[gpu] {gpu_id!r} stockStatus={status!r} (treated as unavailable)")
    available = [
        name for name in spec.pod.gpu_order if by_id.get(name, "").lower() in _AVAILABLE_STOCK
    ]
    if not available:
        raise RuntimeError(
            f"no configured GPU is currently available in {spec.pod.datacenters[0]}; observed={by_id}"
        )
    if all(by_id.get(name, "").lower() == "low" for name in available):
        logger.warning(
            f"[gpu] all configured GPUs in {spec.pod.datacenters[0]} are Low stock — "
            "provisioning may fail"
        )


def scan_consumer_pyproject(ctx: JobContext) -> None:
    """Warn if the consumer's pyproject.toml lists runpod-deploy as a dependency."""
    project_root = Path(ctx.variables["project_root"])
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        logger.info(f"[scan] no pyproject.toml at {pyproject} — skip")
        return
    try:
        data = tomllib.loads(pyproject.read_text())
    except tomllib.TOMLDecodeError as exc:
        logger.warning(f"[scan] pyproject.toml at {pyproject} is not valid TOML: {exc}")
        return
    project = data.get("project") or {}
    deps = project.get("dependencies") or []
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str) and _names_runpod_deploy(dep):
                logger.warning(
                    f"[scan] pyproject.toml: {dep!r} in [project.dependencies] — "
                    "runpod-deploy is a local-only orchestrator; the pod does not need it. "
                    "Remove from dependencies + [tool.uv.sources]."
                )
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, Mapping):
        for group_name, group_deps in optional.items():
            if not isinstance(group_deps, list):
                continue
            for dep in group_deps:
                if isinstance(dep, str) and _names_runpod_deploy(dep):
                    logger.warning(
                        f"[scan] pyproject.toml: {dep!r} in "
                        f"[project.optional-dependencies.{group_name}] — "
                        "runpod-deploy should not ship to the pod."
                    )
    sources = (data.get("tool") or {}).get("uv", {}).get("sources") or {}
    if isinstance(sources, Mapping) and "runpod-deploy" in sources:
        logger.warning(
            "[scan] pyproject.toml: 'runpod-deploy' in [tool.uv.sources] — "
            "remove this entry along with the dependency."
        )
    if _has_torch_dependency(data) and not _has_torch_pinned(data):
        logger.warning(
            "[scan] pyproject.toml: 'torch' is in dependencies but not pinned to a "
            "CUDA-specific wheel via [tool.uv.sources]. RunPod pods (as of 2026-05) "
            "support CUDA up to 12.8; newer torch wheels from default PyPI can fail "
            "torch.cuda.is_available() despite the GPU being functional. See "
            "docs/runpod-gotchas.md for the "
            '[tool.uv.sources] torch = { index = "pytorch-cu128" } pattern.'
        )


def scan_staged_payloads_for_absolute_paths(ctx: JobContext) -> None:
    """Grep staged-source files for hardcoded absolute user paths."""
    project_root = Path(ctx.variables["project_root"])
    seen: set[Path] = set()
    for push in ctx.spec.staging:
        source = ctx.render_path(push.source, base=project_root)
        _scan_path(source, seen)


def _scan_path(source: Path, seen: set[Path]) -> None:
    if not source.exists():
        return
    if source.is_file():
        _scan_file(source, seen)
        return
    for path in source.rglob("*"):
        if path.is_file():
            _scan_file(path, seen)


def _scan_file(path: Path, seen: set[Path]) -> None:
    if path in seen or path.suffix.lower() not in _SCAN_EXTENSIONS:
        return
    seen.add(path)
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > _SCAN_MAX_BYTES:
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    matches = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern in _ABSOLUTE_PATH_PATTERNS:
            match = pattern.search(line)
            if match is None:
                continue
            logger.warning(
                f"[scan] {path}:{lineno}: hardcoded absolute path "
                f"{match.group(0)!r} — will not exist on the pod"
            )
            matches += 1
            if matches >= _MATCHES_PER_FILE:
                return
            break


def _names_runpod_deploy(dependency_string: str) -> bool:
    """Return True when a PEP 508 dependency string names runpod-deploy."""
    head = re.split(r"[<>=!~;\[ ]", dependency_string.strip(), maxsplit=1)[0]
    return head.lower() == "runpod-deploy"


def _names_torch(dependency_string: str) -> bool:
    """Return True when a PEP 508 dependency string names torch (not torchvision etc.)."""
    head = re.split(r"[<>=!~;\[ ]", dependency_string.strip(), maxsplit=1)[0]
    return head.lower() == "torch"


def _has_torch_dependency(data: Mapping[str, Any]) -> bool:
    project = data.get("project") or {}
    deps = project.get("dependencies") or []
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str) and _names_torch(dep):
                return True
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, Mapping):
        for group_deps in optional.values():
            if not isinstance(group_deps, list):
                continue
            for dep in group_deps:
                if isinstance(dep, str) and _names_torch(dep):
                    return True
    return False


def _has_torch_pinned(data: Mapping[str, Any]) -> bool:
    """True when [tool.uv.sources] has any explicit entry for torch."""
    sources = (data.get("tool") or {}).get("uv", {}).get("sources") or {}
    return isinstance(sources, Mapping) and "torch" in sources
