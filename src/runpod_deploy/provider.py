"""RunPod provider operations backed by `runpodctl`."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runpod_deploy.config import STORAGE_EPHEMERAL, STORAGE_NETWORK_VOLUME, JobContext
from runpod_deploy.transport import log_cmd

__all__ = [
    "PodConnection",
    "resolve_volume",
    "run_json",
    "select_gpu_across_datacenters",
    "stop_pod",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PodConnection:
    """SSH-ready RunPod connection details."""

    pod_id: str
    host: str
    port: int
    gpu_id: str


def select_gpu_across_datacenters(
    datacenters_payload: Sequence[dict[str, object]],
    *,
    datacenters: Sequence[str],
    gpu_order: Sequence[str],
    on_failover: Callable[[str, str | None, str], None] | None = None,
    prices: Mapping[str, float] | None = None,
    max_gpu_price_usd: float | None = None,
) -> tuple[str, str]:
    """Select first available (gpu_id, datacenter_id) across the failover list.

    Iterates ``datacenters`` in order; within each DC iterates ``gpu_order``
    and returns the first GPU with non-empty/non-"out" stock. When a DC
    yields no match, calls ``on_failover(failed_dc, next_dc, reason)``
    before moving on.

    When both ``prices`` (a ``{gpu_id: usd_per_hour}`` map) and
    ``max_gpu_price_usd`` are supplied, GPUs whose price exceeds the
    ceiling are skipped (with a per-GPU ``on_failover`` event reason
    ``"price > $X.XX/hr"``). GPUs missing from ``prices`` are NOT
    skipped — absent price data is treated as "unknown, allow."

    Raises RuntimeError when nothing matches across all DCs.
    """
    if not datacenters:
        raise ValueError("datacenters must contain at least one id")
    last_observed: dict[str, dict[str, str]] = {}
    for i, dc_id in enumerate(datacenters):
        next_dc = datacenters[i + 1] if i + 1 < len(datacenters) else None
        dc_payload = _find_datacenter(datacenters_payload, dc_id)
        if dc_payload is None:
            reason = f"datacenter {dc_id!r} not found in runpodctl datacenter list"
            if on_failover is not None:
                on_failover(dc_id, next_dc, reason)
            continue
        availability = dc_payload.get("gpuAvailability") or []
        if not isinstance(availability, list):
            reason = f"datacenter {dc_id!r} gpuAvailability has unexpected type"
            if on_failover is not None:
                on_failover(dc_id, next_dc, reason)
            continue
        by_id = {
            str(item.get("gpuId")): str(item.get("stockStatus") or "").strip()
            for item in availability
            if isinstance(item, dict)
        }
        last_observed[dc_id] = by_id
        for gpu_id in gpu_order:
            stock = by_id.get(gpu_id, "")
            if not stock or stock.lower() in {"none", "unavailable", "out"}:
                continue
            if max_gpu_price_usd is not None and prices is not None:
                price = prices.get(gpu_id)
                if price is not None and price > max_gpu_price_usd:
                    if on_failover is not None:
                        reason = (
                            f"{gpu_id!r} price ${price:.2f}/hr > ${max_gpu_price_usd:.2f}/hr cap"
                        )
                        on_failover(dc_id, next_dc, reason)
                    continue
            return gpu_id, dc_id
        reason = f"no configured GPU available in {dc_id}; observed={by_id}"
        if on_failover is not None:
            on_failover(dc_id, next_dc, reason)
    raise RuntimeError(_no_match_message(list(datacenters), gpu_order, last_observed))


def _find_datacenter(payload: Sequence[dict[str, object]], dc_id: str) -> dict[str, object] | None:
    for dc in payload:
        if dc.get("id") == dc_id:
            return dc
    return None


def _no_match_message(
    datacenters: list[str],
    gpu_order: Sequence[str],
    last_observed: dict[str, dict[str, str]],
) -> str:
    """Format the diagnostic when nothing matches across all DCs."""
    base = (
        f"no configured GPU available across datacenters {datacenters} "
        f"for gpu_order {list(gpu_order)}"
    )
    if not last_observed:
        return base
    tier_rank = {"high": 0, "medium": 1, "low": 2}
    lines = [base, "  observed availability:"]
    for dc_id, by_id in last_observed.items():
        lines.append(f"  - {dc_id}:")
        sorted_pairs = sorted(
            ((name, status) for name, status in by_id.items() if status.lower() in tier_rank),
            key=lambda item: (tier_rank[item[1].lower()], item[0]),
        )
        for name, status in sorted_pairs:
            lines.append(f"      {name} ({status})")
    return "\n".join(lines)


def resolve_volume(
    volumes: Sequence[dict[str, object]],
    *,
    volume_name: str,
    expected_datacenter_id: str,
) -> tuple[str, str]:
    """Resolve a RunPod network-volume name to id/datacenter and enforce location."""
    for volume in volumes:
        if volume.get("name") == volume_name:
            volume_id = str(volume.get("id") or "")
            datacenter_id = str(volume.get("dataCenterId") or "")
            if datacenter_id != expected_datacenter_id:
                raise RuntimeError(
                    f"volume {volume_name!r} is in {datacenter_id}, expected {expected_datacenter_id}"
                )
            if not volume_id:
                raise RuntimeError(f"volume {volume_name!r} has no id in runpodctl output")
            return volume_id, datacenter_id
    observed = [str(v.get("name")) for v in volumes]
    raise RuntimeError(f"volume {volume_name!r} not found; observed={observed}")


def _supported_pod_create_flags() -> frozenset[str]:
    """Return the set of flags supported by the installed ``runpodctl pod create``.

    Parses ``runpodctl pod create --help`` and extracts every long-form flag
    (``--name``). Cached for the lifetime of the process; the result is a
    function of the locally-installed runpodctl binary.

    Returns
    -------
    frozenset[str]
        Set of flag names without the leading dashes (e.g.,
        ``"gpu-id"``, ``"data-center-ids"``, ...). Empty set on probe
        failure (treated as "permissive" — emit flags and let runpodctl
        decide; matches pre-v0.3.2 behavior).
    """
    cached: frozenset[str] | None = _supported_pod_create_flags._cached  # type: ignore[attr-defined]
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            ["runpodctl", "pod", "create", "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "runpodctl flag probe failed (%s); emitting all configured flags "
            "without feature detection",
            type(exc).__name__,
        )
        flags: frozenset[str] = frozenset()
        _supported_pod_create_flags._cached = flags  # type: ignore[attr-defined]
        return flags
    # Each flag line looks like:  "      --gpu-id string          gpu id (...)"
    # We split on whitespace and pick tokens that start with "--".
    found: set[str] = set()
    for line in (result.stdout + result.stderr).splitlines():
        for token in line.split():
            if token.startswith("--") and len(token) > 2:
                # Strip trailing punctuation if any (e.g., "--gpu-id,").
                name = token[2:].rstrip(",")
                if name and all(c.isalnum() or c == "-" for c in name):
                    found.add(name)
    flags = frozenset(found)
    _supported_pod_create_flags._cached = flags  # type: ignore[attr-defined]
    return flags


# Function-level cache. Reset in tests via ``_supported_pod_create_flags._cached = None``.
_supported_pod_create_flags._cached = None  # type: ignore[attr-defined]


def _maybe_extend(
    argv: list[str],
    name: str,
    *values: str,
    supported: frozenset[str],
    yaml_key: str | None = None,
) -> None:
    """Append ``--name [values...]`` to ``argv`` iff runpodctl supports it.

    Logs a WARNING when a configured flag is skipped because the local
    runpodctl doesn't recognize it. Empty ``supported`` (probe failure)
    is treated as permissive.
    """
    if supported and name not in supported:
        logger.warning(
            "runpodctl pod create does not support --%s in the locally-installed "
            "version; skipping (set in YAML as 'pod.%s'). Upgrade runpodctl when "
            "the flag becomes available, or omit the YAML key to silence this.",
            name,
            yaml_key or name.replace("-", "_"),
        )
        return
    argv.append(f"--{name}")
    argv.extend(values)


def _build_pod_create_argv(
    ctx: JobContext, *, volume_id: str | None, gpu_id: str, datacenter_id: str
) -> list[str]:
    """Build the `runpodctl pod create` argv with feature-detected flag gating."""
    spec = ctx.spec
    supported = _supported_pod_create_flags()
    argv = [
        "runpodctl",
        "pod",
        "create",
        "--gpu-id",
        gpu_id,
    ]
    if spec.pod.gpu_count > 1:
        argv.extend(["--gpu-count", str(spec.pod.gpu_count)])
    if spec.pod.spot:
        _maybe_extend(argv, "spot", supported=supported, yaml_key="spot")
    if spec.pod.min_vcpu_count is not None:
        _maybe_extend(
            argv,
            "min-vcpu-count",
            str(spec.pod.min_vcpu_count),
            supported=supported,
            yaml_key="min_vcpu_count",
        )
    if spec.pod.min_memory_gb is not None:
        _maybe_extend(
            argv,
            "min-memory-in-gb",
            str(spec.pod.min_memory_gb),
            supported=supported,
            yaml_key="min_memory_gb",
        )
    argv.extend(
        [
            "--image",
            spec.pod.image,
            "--data-center-ids",
            datacenter_id,
            "--volume-mount-path",
            spec.storage.volume_mount,
            f"--cloud-type={spec.pod.cloud_type}",
        ]
    )
    for port in spec.pod.ports:
        argv.extend(["--ports", port])
    argv.extend(["--name", ctx.run_id])
    if spec.storage.mode == STORAGE_NETWORK_VOLUME:
        if not volume_id:
            raise ValueError("network-volume provisioning requires volume_id")
        argv.extend(["--network-volume-id", volume_id])
    elif spec.storage.mode == STORAGE_EPHEMERAL:
        if spec.storage.volume_gb is None:
            raise ValueError("ephemeral provisioning requires storage.volume_gb")
        argv.extend(["--volume-in-gb", str(spec.storage.volume_gb)])
    else:
        raise ValueError(f"unsupported storage mode: {spec.storage.mode!r}")
    argv.extend(["--container-disk-in-gb", str(spec.pod.container_disk_gb)])
    return argv


def provision_pod(
    ctx: JobContext,
    *,
    volume_id: str | None,
    gpu_id: str,
    datacenter_id: str,
    dry_run: bool,
) -> PodConnection:
    """Provision a pod and return SSH connection details."""
    argv = _build_pod_create_argv(
        ctx, volume_id=volume_id, gpu_id=gpu_id, datacenter_id=datacenter_id
    )
    log_cmd(logger, "runpodctl", argv)
    if dry_run:
        return PodConnection(pod_id="<pod-id>", host="203.0.113.10", port=22022, gpu_id=gpu_id)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"pod create failed exit={result.returncode}: stdout={result.stdout} stderr={result.stderr}"
        )
    payload = json.loads(result.stdout)
    pod_id = str(payload.get("id") or payload.get("podId") or "")
    if not pod_id:
        raise RuntimeError(f"pod create returned no pod id: {payload}")
    pod = _wait_for_pod_ready(pod_id, gpu_id=gpu_id)
    state_file = ctx.spec.resolved_state_file
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"pod_id": pod.pod_id, "gpu_id": gpu_id}, indent=2))
    return pod


def _wait_for_pod_ready(pod_id: str, *, gpu_id: str) -> PodConnection:
    """Wait until RunPod reports a pod as running with SSH host/port."""
    deadline = time.time() + 240
    last_payload: dict[str, object] = {}
    while time.time() < deadline:
        payload = run_json(["runpodctl", "pod", "get", pod_id, "-o", "json"])
        if isinstance(payload, dict):
            last_payload = payload
            status = payload.get("desiredStatus") or payload.get("status")
            ssh_payload = payload.get("ssh")
            ssh_info = ssh_payload if isinstance(ssh_payload, dict) else {}
            host = str(ssh_info.get("ip") or payload.get("publicIp") or "")
            port_raw = ssh_info.get("port")
            port = int(port_raw or 0)
            if status == "RUNNING" and host and port:
                logger.info(f"[pod] {pod_id} RUNNING ssh={host}:{port} gpu={gpu_id}")
                return PodConnection(pod_id=pod_id, host=host, port=port, gpu_id=gpu_id)
        time.sleep(5)
    raise RuntimeError(f"pod {pod_id} did not become SSH-ready; last={last_payload}")


def stop_pod(pod_id: str, *, dry_run: bool, state_file: Path | None = None) -> None:
    """Stop a RunPod pod and optionally clear its state file."""
    argv = ["runpodctl", "pod", "stop", pod_id]
    log_cmd(logger, "runpodctl", argv)
    if dry_run or pod_id == "<pod-id>":
        return
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        logger.warning(
            f"[warn] failed to stop pod {pod_id}: stdout={result.stdout} stderr={result.stderr}"
        )
    elif state_file is not None:
        state_file.unlink(missing_ok=True)


def run_json(argv: list[str]) -> Any:
    """Run a local command and parse JSON."""
    log_cmd(logger, "local", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {argv}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    payload = json.loads(result.stdout)
    logger.debug(f"[local] argv={argv[0]!r} payload_type={type(payload).__name__}")
    return payload
