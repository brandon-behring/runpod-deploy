"""Opt-in pre-run checks: GPU availability, consumer-pyproject scan, path scan."""

from __future__ import annotations

import difflib
import fnmatch
import logging
import re
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runpod_deploy.config import DEFAULT_STAGING_EXCLUDES, JobContext, RunpodJobSpec
from runpod_deploy.provider import run_json

__all__ = [
    "DatacenterInventory",
    "InventoryReport",
    "check_gpu_availability",
    "check_image_registry",
    "fetch_datacenter_payload",
    "report_gpu_inventory",
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

# Universal noise: applied to every staging file walk regardless of the
# consumer's `excludes_default` setting. The scanner has no business reading
# files in these directories — they never reach the pod via rsync's default
# behavior in practice. Keep aligned with `config.DEFAULT_STAGING_EXCLUDES`
# so the scanner and rsync agree on what counts as universal hygiene noise.
_UNIVERSAL_NOISE_EXCLUDES: tuple[str, ...] = DEFAULT_STAGING_EXCLUDES

_UV_SYNC_RE = re.compile(r"\buv\s+sync\b(?P<args>[^\n]*)")
_EXTRA_FLAG_RE = re.compile(r"--extra(?:\s+|=)(?P<name>[A-Za-z0-9_-]+)")
_ALL_EXTRAS_RE = re.compile(r"--all-extras\b")


@dataclass(frozen=True, slots=True)
class _InstallExtraSet:
    """Parsed set of optional-dependencies extras the pod will install.

    Built by parsing every ``setup[*].command`` and ``run.body`` for
    ``uv sync --extra <name>`` (and ``--all-extras``) invocations.
    """

    has_uv_sync: bool
    all_extras: bool
    named_extras: frozenset[str]


@dataclass(frozen=True, slots=True)
class DatacenterInventory:
    """Per-datacenter snapshot of GPU stock vs. a configured gpu_order.

    Built by intersecting the configured ``pod.gpu_order`` with the live
    ``gpuAvailability`` array returned by ``runpodctl datacenter list``
    for one datacenter id.

    Attributes mirror the four states a configured GPU can be in for one
    DC, plus a fifth "widening hint" listing GPUs the DC has stocked but
    the config does not request.
    """

    datacenter_id: str
    configured_available: tuple[str, ...]
    configured_low_stock: tuple[str, ...]
    configured_stockout: tuple[str, ...]
    configured_unknown: tuple[str, ...]
    other_available: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InventoryReport:
    """Aggregated GPU-stock snapshot across all configured datacenters.

    Used by ``runpod-deploy gpu-inventory`` to answer the question
    "will any configured GPU provision right now?" without raising.
    """

    gpu_order: tuple[str, ...]
    datacenters: tuple[DatacenterInventory, ...]

    @property
    def any_stocked(self) -> bool:
        """Whether at least one configured GPU is available in any DC.

        Mirrors the semantics of ``check_gpu_availability``: when this is
        False, a real ``runpod-deploy run`` would exhaust failover and
        fail with a stock-out diagnostic.
        """
        return any(dc.configured_available or dc.configured_low_stock for dc in self.datacenters)


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
    """Validate every gpu_order entry against live RunPod stock data.

    Iterates ``spec.pod.datacenters`` (the failover list). Passes when at
    least one DC has at least one ``gpu_order`` GPU with available stock;
    raises when no DC has any available GPU.
    """
    spec = ctx.spec
    any_available = False
    for dc_id in spec.pod.datacenters:
        if _check_one_datacenter(spec.pod.gpu_order, dc_id):
            any_available = True
    if not any_available:
        raise RuntimeError(
            f"no configured GPU is currently available in any datacenter of "
            f"{list(spec.pod.datacenters)}"
        )


def _check_one_datacenter(gpu_order: tuple[str, ...], dc_id: str) -> bool:
    """Report on one DC's availability; return True when at least one configured GPU is up."""
    entry = fetch_datacenter_payload(dc_id)
    availability = entry.get("gpuAvailability") or []
    if not isinstance(availability, list):
        raise RuntimeError(
            f"datacenter {dc_id!r} gpuAvailability is "
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
    for gpu_id in gpu_order:
        if gpu_id not in by_id:
            suggestions = difflib.get_close_matches(gpu_id, known_names, n=1, cutoff=0.6)
            hint = f" — did you mean {suggestions[0]!r}?" if suggestions else ""
            logger.error(f"[gpu:{dc_id}] {gpu_id!r} not in datacenter{hint}")
            continue
        status = by_id[gpu_id]
        if status.lower() in _UNAVAILABLE_STOCK:
            logger.warning(
                f"[gpu:{dc_id}] {gpu_id!r} stockStatus={status!r} (treated as unavailable)"
            )
    available = [name for name in gpu_order if by_id.get(name, "").lower() in _AVAILABLE_STOCK]
    if not available:
        logger.warning(f"[gpu:{dc_id}] no configured GPU available; observed={by_id}")
        return False
    if all(by_id.get(name, "").lower() == "low" for name in available):
        logger.warning(f"[gpu:{dc_id}] all configured GPUs are Low stock — provisioning may fail")
    return True


def report_gpu_inventory(ctx: JobContext) -> InventoryReport:
    """Build a structured stock report without raising on empty intersection.

    Sibling to ``check_gpu_availability``: same probe, different return
    shape. Where ``check_gpu_availability`` raises on cluster-wide
    stock-out (used by ``runpod-deploy validate --check-availability``),
    this returns an ``InventoryReport`` callers can inspect, print, or
    feed into a non-zero exit (used by ``runpod-deploy gpu-inventory``).
    """
    spec = ctx.spec
    per_dc = tuple(
        _inventory_one_datacenter(spec.pod.gpu_order, dc_id) for dc_id in spec.pod.datacenters
    )
    return InventoryReport(gpu_order=spec.pod.gpu_order, datacenters=per_dc)


def _inventory_one_datacenter(gpu_order: tuple[str, ...], dc_id: str) -> DatacenterInventory:
    """Build a structured per-DC inventory snapshot from live RunPod stock."""
    entry = fetch_datacenter_payload(dc_id)
    availability = entry.get("gpuAvailability") or []
    if not isinstance(availability, list):
        raise RuntimeError(
            f"datacenter {dc_id!r} gpuAvailability is "
            f"{type(availability).__name__}, expected list"
        )
    by_id: dict[str, str] = {}
    for item in availability:
        if isinstance(item, dict):
            name = str(item.get("gpuId") or "")
            status = str(item.get("stockStatus") or "").strip().lower()
            if name:
                by_id[name] = status
    configured_set = set(gpu_order)
    configured_available = tuple(
        g for g in gpu_order if by_id.get(g, "") in _AVAILABLE_STOCK and by_id[g] != "low"
    )
    configured_low_stock = tuple(g for g in gpu_order if by_id.get(g, "") == "low")
    configured_stockout = tuple(
        g for g in gpu_order if g in by_id and by_id[g] in _UNAVAILABLE_STOCK
    )
    configured_unknown = tuple(g for g in gpu_order if g not in by_id)
    other_available = tuple(
        sorted(
            name
            for name, status in by_id.items()
            if name not in configured_set and status in _AVAILABLE_STOCK
        )
    )
    return DatacenterInventory(
        datacenter_id=dc_id,
        configured_available=configured_available,
        configured_low_stock=configured_low_stock,
        configured_stockout=configured_stockout,
        configured_unknown=configured_unknown,
        other_available=other_available,
    )


def scan_consumer_pyproject(ctx: JobContext) -> None:
    """Warn if the consumer's pyproject.toml lists runpod-deploy as a dependency.

    Optional-dependencies groups (``[project.optional-dependencies.<name>]``)
    are only flagged when ``<name>`` is actually installed on the pod —
    determined by parsing ``setup[*].command`` and ``run.body`` for
    ``uv sync --extra <name>`` (or ``--all-extras``). When no ``uv sync``
    invocation is detected, optional-extras scans are suppressed (no
    signal that anything beyond ``[project.dependencies]`` reaches the pod).
    """
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
    installed = _parsed_install_extras(ctx.spec)
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
            if not _extra_reaches_pod(str(group_name), installed):
                continue
            for dep in group_deps:
                if isinstance(dep, str) and _names_runpod_deploy(dep):
                    logger.warning(
                        f"[scan] pyproject.toml: {dep!r} in "
                        f"[project.optional-dependencies.{group_name}] — "
                        f"the run-body installs this extra (`uv sync --extra {group_name}`), "
                        "so runpod-deploy will ship to the pod. "
                        "Move it out of an installed extra, or drop the --extra flag."
                    )
    sources = (data.get("tool") or {}).get("uv", {}).get("sources") or {}
    if isinstance(sources, Mapping) and "runpod-deploy" in sources:
        logger.warning(
            "[scan] pyproject.toml: 'runpod-deploy' in [tool.uv.sources] — "
            "remove this entry along with the dependency."
        )
    if _has_torch_dependency(data, installed) and not _has_torch_pinned(data):
        logger.warning(
            "[scan] pyproject.toml: 'torch' is in dependencies but not pinned to a "
            "CUDA-specific wheel via [tool.uv.sources]. RunPod pods (as of 2026-05) "
            "support CUDA up to 12.8; newer torch wheels from default PyPI can fail "
            "torch.cuda.is_available() despite the GPU being functional. See "
            "docs/runpod-gotchas.md for the "
            '[tool.uv.sources] torch = { index = "pytorch-cu128" } pattern.'
        )
    _warn_fuse_uv_link_mode(ctx.spec, installed)


def _warn_fuse_uv_link_mode(spec: RunpodJobSpec, installed: _InstallExtraSet) -> None:
    """Warn when uv sync runs on a FUSE-mounted /workspace without UV_LINK_MODE=copy.

    Detects the conjunction documented by Issue #92 / PR #93:
    1. ``storage.volume_mount`` is under ``/workspace`` (RunPod's FUSE mount).
    2. ``setup[*].command`` or ``run.body`` invokes ``uv sync``.
    3. ``UV_LINK_MODE`` is NOT exported via ``remote_env.exports`` AND not set
       inline before any ``uv sync`` invocation in the setup/run text.

    Under default uv hardlink mode on FUSE, ``uv sync`` can hang silently
    partway through wheel extraction. The fix is ``UV_LINK_MODE=copy``;
    this warning surfaces it before any pod fires. Issue #94.
    """
    if not _volume_mount_is_fuse(spec.storage.volume_mount):
        return
    if not installed.has_uv_sync:
        return
    if _uv_link_mode_set(spec):
        return
    logger.warning(
        f"[scan] uv sync runs on a FUSE-mounted volume_mount={spec.storage.volume_mount!r} "
        "without UV_LINK_MODE=copy. RunPod's /workspace is a distributed FUSE filesystem; "
        "uv's default hardlink mode can hang silently partway through wheel install. "
        "Add `UV_LINK_MODE: copy` to remote_env.exports (or export it inline before "
        "`uv sync` in setup). See docs/source/troubleshooting.md "
        '"uv sync hangs silently with .venv partially populated".'
    )


def _volume_mount_is_fuse(volume_mount: str) -> bool:
    """Whether ``volume_mount`` resolves to RunPod's FUSE-backed /workspace.

    All RunPod-managed network volumes mount under ``/workspace`` (or a
    subdirectory of it) as a FUSE filesystem. Ephemeral storage uses the
    same path by convention. Anything outside ``/workspace`` is operator-
    controlled and we don't make assumptions about it.
    """
    return volume_mount == "/workspace" or volume_mount.startswith("/workspace/")


_UV_LINK_MODE_INLINE_RE = re.compile(r"(?:^|\s|;|&|&&)UV_LINK_MODE\s*=\s*(?:[\"\']?copy[\"\']?)\b")


def _uv_link_mode_set(spec: RunpodJobSpec) -> bool:
    """Whether UV_LINK_MODE is set (in remote_env.exports OR inline before uv sync)."""
    if "UV_LINK_MODE" in spec.remote_env.exports:
        return True
    for cmd in spec.setup:
        if _UV_LINK_MODE_INLINE_RE.search(cmd.command):
            return True
    return bool(_UV_LINK_MODE_INLINE_RE.search(spec.run.body))


def scan_staged_payloads_for_absolute_paths(ctx: JobContext) -> None:
    """Grep staged-source files for hardcoded absolute user paths.

    Honors the consumer's ``excludes_default`` / ``excludes`` / ``excludes_extra``
    via ``RsyncPushSpec.effective_excludes`` so files that rsync would skip
    aren't scanned. Always also skips a universal-noise set
    (``_UNIVERSAL_NOISE_EXCLUDES``, mirrors ``DEFAULT_STAGING_EXCLUDES``) so
    ``.venv/``, ``.mypy_cache/`` etc. are quiet even when the consumer's
    staging config hasn't opted into ``excludes_default``.
    """
    project_root = Path(ctx.variables["project_root"])
    seen: set[Path] = set()
    for push in ctx.spec.staging:
        source = ctx.render_path(push.source, base=project_root)
        _scan_path(source, seen, excludes=push.effective_excludes)


def _scan_path(source: Path, seen: set[Path], *, excludes: Sequence[str]) -> None:
    if not source.exists():
        return
    if source.is_file():
        _scan_file(source, seen)
        return
    all_excludes = tuple(excludes) + _UNIVERSAL_NOISE_EXCLUDES
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if _path_matches_rsync_exclude(rel, all_excludes):
            continue
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


def _path_matches_rsync_exclude(rel_path: Path, patterns: Iterable[str]) -> bool:
    """Return True when ``rel_path`` matches any rsync-style exclude pattern.

    Supports the subset of rsync filter rules used by ``DEFAULT_STAGING_EXCLUDES``
    and typical consumer ``excludes_extra`` lists:

    - Trailing ``/`` → directory-only (the matched component must have children
      in the rel_path; matches when rel_path is *inside* the directory).
    - ``**/`` prefix → match anywhere (treated as basename / any-component).
    - Embedded ``/`` (no ``**``) → root-anchored path-prefix match.
    - No ``/`` → match any component of the path (basename or any ancestor).
    - ``*`` glob in a single component via :func:`fnmatch.fnmatchcase`.
    """
    path_parts = rel_path.parts
    for pattern in patterns:
        dir_only = pattern.endswith("/")
        pat = pattern.rstrip("/")
        if not pat:
            continue
        if pat.startswith("**/"):
            inner = pat[3:]
            if _matches_anywhere(inner, path_parts, dir_only=dir_only):
                return True
        elif "/" in pat:
            if _matches_prefix(pat.split("/"), path_parts, dir_only=dir_only):
                return True
        else:
            if _matches_anywhere(pat, path_parts, dir_only=dir_only):
                return True
    return False


def _matches_anywhere(pat: str, path_parts: tuple[str, ...], *, dir_only: bool) -> bool:
    """Match a (possibly multi-component) pattern against any window of path_parts.

    If ``dir_only`` is set, the matched window must end before the final path
    component (i.e., the match identifies an ancestor directory of the file).
    """
    if "/" in pat:
        pat_parts = pat.split("/")
        n_pat = len(pat_parts)
        n_path = len(path_parts)
        for start in range(n_path - n_pat + 1):
            window = path_parts[start : start + n_pat]
            if all(fnmatch.fnmatchcase(window[i], pat_parts[i]) for i in range(n_pat)):
                end = start + n_pat - 1
                if dir_only and end == n_path - 1:
                    continue
                return True
        return False
    n = len(path_parts)
    for i, part in enumerate(path_parts):
        if dir_only and i == n - 1:
            continue
        if fnmatch.fnmatchcase(part, pat):
            return True
    return False


def _matches_prefix(pat_parts: list[str], path_parts: tuple[str, ...], *, dir_only: bool) -> bool:
    """Root-anchored path-prefix match with `**` expansion for any-depth wildcards."""
    if not pat_parts:
        return not dir_only
    head, *rest = pat_parts
    if head == "**":
        if not rest:
            return True
        for skip in range(len(path_parts) + 1):
            if _matches_prefix(rest, path_parts[skip:], dir_only=dir_only):
                return True
        return False
    if not path_parts:
        return False
    if not fnmatch.fnmatchcase(path_parts[0], head):
        return False
    if not rest:
        if dir_only:
            return len(path_parts) > 1
        return True
    return _matches_prefix(rest, path_parts[1:], dir_only=dir_only)


def _parsed_install_extras(spec: RunpodJobSpec) -> _InstallExtraSet:
    """Parse `uv sync --extra <name>` / `--all-extras` flags from setup + run.body."""
    texts: list[str] = [cmd.command for cmd in spec.setup]
    texts.append(spec.run.body)
    has_uv_sync = False
    all_extras = False
    named: set[str] = set()
    for text in texts:
        for sync_match in _UV_SYNC_RE.finditer(text):
            has_uv_sync = True
            args = sync_match.group("args")
            if _ALL_EXTRAS_RE.search(args):
                all_extras = True
            for extra_match in _EXTRA_FLAG_RE.finditer(args):
                named.add(extra_match.group("name"))
    return _InstallExtraSet(
        has_uv_sync=has_uv_sync,
        all_extras=all_extras,
        named_extras=frozenset(named),
    )


def _extra_reaches_pod(group_name: str, installed: _InstallExtraSet) -> bool:
    """Whether an optional-deps group is installed on the pod.

    Returns False when no `uv sync` invocation was detected — without that
    signal we cannot tell which extras (if any) install on the pod, so
    silence is correct.
    """
    if installed.all_extras:
        return True
    return group_name in installed.named_extras


def _names_runpod_deploy(dependency_string: str) -> bool:
    """Return True when a PEP 508 dependency string names runpod-deploy."""
    head = re.split(r"[<>=!~;\[ ]", dependency_string.strip(), maxsplit=1)[0]
    return head.lower() == "runpod-deploy"


def _names_torch(dependency_string: str) -> bool:
    """Return True when a PEP 508 dependency string names torch (not torchvision etc.)."""
    head = re.split(r"[<>=!~;\[ ]", dependency_string.strip(), maxsplit=1)[0]
    return head.lower() == "torch"


def _has_torch_dependency(data: Mapping[str, Any], installed: _InstallExtraSet) -> bool:
    """True iff torch reaches the pod: in [project.dependencies], or in an installed extra."""
    project = data.get("project") or {}
    deps = project.get("dependencies") or []
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str) and _names_torch(dep):
                return True
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, Mapping):
        for group_name, group_deps in optional.items():
            if not isinstance(group_deps, list):
                continue
            if not _extra_reaches_pod(str(group_name), installed):
                continue
            for dep in group_deps:
                if isinstance(dep, str) and _names_torch(dep):
                    return True
    return False


def _has_torch_pinned(data: Mapping[str, Any]) -> bool:
    """True when [tool.uv.sources] has any explicit entry for torch."""
    sources = (data.get("tool") or {}).get("uv", {}).get("sources") or {}
    return isinstance(sources, Mapping) and "torch" in sources


_DOCKER_HUB_TAG_URL = "https://hub.docker.com/v2/repositories/{owner}/{image}/tags/{tag}/"
_REGISTRY_CHECK_TIMEOUT_SEC = 5.0
_REGISTRY_CHECK_CACHE: dict[str, tuple[str, str | None]] = {}


@dataclass(frozen=True, slots=True)
class _DockerImageRef:
    """Parsed Docker image reference (Docker Hub only).

    Non-Docker-Hub registries (any image string with an explicit
    ``<host>/`` prefix containing ``.`` or ``:``) parse to ``None``;
    they are skipped with an INFO log because we have no portable
    cross-registry tag API.
    """

    owner: str
    image: str
    tag: str


def _parse_docker_image(image: str) -> _DockerImageRef | None:
    """Parse ``<owner>/<image>:<tag>``-style Docker Hub references.

    Returns None for non-Docker-Hub registries (detected by a leading
    ``<host>/`` prefix where ``<host>`` contains ``.`` or ``:``). Tags
    default to ``latest`` when omitted; library images
    (``python:3.11``) default the owner to ``library``.
    """
    if not image:
        return None
    head, _, rest = image.partition("/")
    if rest and ("." in head or ":" in head):
        return None
    if rest:
        owner = head
        name_with_tag = rest
    else:
        owner = "library"
        name_with_tag = image
    if "/" in name_with_tag:
        return None
    name, sep, tag = name_with_tag.partition(":")
    if not name:
        return None
    return _DockerImageRef(owner=owner, image=name, tag=tag if sep else "latest")


def _check_docker_hub_tag(ref: _DockerImageRef) -> tuple[str, str | None]:
    """HEAD-check a Docker Hub tag. Returns ``(status, detail)``.

    Status is one of ``"ok"`` (200), ``"missing"`` (404), or
    ``"unknown"`` (any other outcome — typically offline / rate-limit /
    timeout). The detail is a short diagnostic string for non-200
    outcomes; ``None`` on success.
    """
    url = _DOCKER_HUB_TAG_URL.format(owner=ref.owner, image=ref.image, tag=ref.tag)
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=_REGISTRY_CHECK_TIMEOUT_SEC) as resp:
            code = resp.getcode()
            if code == 200:
                return ("ok", None)
            return ("unknown", f"HTTP {code}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return ("missing", "HTTP 404")
        return ("unknown", f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return ("unknown", f"network: {exc}")


def check_image_registry(ctx: JobContext) -> None:
    """HEAD-check ``pod.image`` against Docker Hub.

    Catches phantom tags that pass schema validation today but get
    stuck in image-pull-backoff on the pod (RunPod's API accepts any
    image string at ``pod create`` time). Off by default for offline /
    CI scenarios — opt in via ``runpod-deploy validate --all`` or
    ``runpod-deploy validate --check-image-registry``.

    Outcomes:

    - 200 → INFO ``ok: image <name> exists on Docker Hub``
    - 404 → WARNING with the literal $0.62 cost-evidence pointer
    - other (offline, rate-limit, non-Docker-Hub host) → INFO; do not
      block the run

    Results are cached per-process so multiple validate calls in the
    same Python session (sweep harness, pytest) only HEAD the
    registry once per unique image string.
    """
    image = ctx.spec.pod.image
    if not image:
        return
    cached = _REGISTRY_CHECK_CACHE.get(image)
    if cached is not None:
        status, detail = cached
    else:
        ref = _parse_docker_image(image)
        if ref is None:
            logger.info(
                f"[image-registry] {image!r}: not on Docker Hub "
                "(non-default registry or malformed tag) — skip"
            )
            _REGISTRY_CHECK_CACHE[image] = ("skipped", None)
            return
        status, detail = _check_docker_hub_tag(ref)
        _REGISTRY_CHECK_CACHE[image] = (status, detail)
    if status == "ok":
        logger.info(f"[image-registry] ok: {image!r} exists on Docker Hub")
    elif status == "missing":
        logger.warning(
            f"[image-registry] {image!r} does NOT exist on Docker Hub "
            "(HEAD returned 404). RunPod's API accepts any image string at "
            "pod-create time, so the pod will provision but stay stuck in "
            "image-pull-backoff with `uptimeSeconds: 0` and `ssh.error: pod "
            "not ready` indefinitely (~$0.30/pod burned before diagnosis on "
            "consumer-reported 2026-05-17 incident). Fix the tag before "
            "running. Pass --skip-registry-check to suppress this check."
        )
    elif status == "skipped":
        pass
    else:
        logger.info(
            f"[image-registry] could not verify {image!r} on Docker Hub "
            f"({detail}) — likely offline / behind a firewall / rate-limited. "
            "Pass --skip-registry-check to silence this in CI."
        )
