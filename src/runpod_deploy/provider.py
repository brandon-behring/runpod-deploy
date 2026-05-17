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

from runpod_deploy.config import (
    STORAGE_EPHEMERAL,
    STORAGE_NETWORK_VOLUME,
    JobContext,
    LifecycleAction,
)
from runpod_deploy.pricing import estimate_volume_storage_cost_usd_per_day
from runpod_deploy.transport import log_cmd

__all__ = [
    "PodConnection",
    "StalePod",
    "bulk_delete_pods",
    "cleanup_pod",
    "list_stale_pods",
    "resolve_volume",
    "run_json",
    "select_gpu_across_datacenters",
    "try_resume_pod",
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
    ctx: JobContext,
    *,
    volume_id: str | None,
    gpu_id: str,
    datacenter_id: str,
    cloud_type_override: str | None = None,
) -> list[str]:
    """Build the `runpodctl pod create` argv with feature-detected flag gating.

    When ``cloud_type_override`` is set, it replaces ``spec.pod.cloud_type``
    in the emitted ``--cloud-type=`` flag. Used by the orchestrator's
    ``--fallback-cloud-type`` retry path to invoke pod create against a
    different cloud_type than the YAML configured.
    """
    spec = ctx.spec
    supported = _supported_pod_create_flags()
    cloud_type = cloud_type_override or spec.pod.cloud_type
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
            f"--cloud-type={cloud_type}",
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
    ssh_ready_timeout_sec: int = 900,
    cloud_type_override: str | None = None,
) -> PodConnection:
    """Provision a pod and return SSH connection details.

    ``ssh_ready_timeout_sec`` bounds the wait for the pod's SSH proxy
    to publish a host/port after ``runpodctl pod create`` succeeds.
    The default 900 s covers cold-pull of large pytorch/cudnn images
    on first-touch GPUs. If the deadline expires, the just-created pod
    is deleted before the ``RuntimeError`` is re-raised so the orphan
    doesn't bill indefinitely.

    Set ``cloud_type_override`` to invoke ``runpodctl pod create`` with a
    different ``--cloud-type=`` than ``spec.pod.cloud_type``. Used by the
    orchestrator's ``--fallback-cloud-type`` retry path.
    """
    argv = _build_pod_create_argv(
        ctx,
        volume_id=volume_id,
        gpu_id=gpu_id,
        datacenter_id=datacenter_id,
        cloud_type_override=cloud_type_override,
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
    try:
        pod = _wait_for_pod_ready(pod_id, gpu_id=gpu_id, timeout_sec=ssh_ready_timeout_sec)
    except Exception:
        logger.warning(
            f"[lifecycle] pod {pod_id!r} failed to reach SSH-ready; "
            f"deleting to release compute + disk billing before re-raising"
        )
        delete_argv = ["runpodctl", "pod", "delete", pod_id]
        log_cmd(logger, "runpodctl", delete_argv)
        delete_result = subprocess.run(delete_argv, capture_output=True, text=True, check=False)
        if delete_result.returncode != 0:
            logger.warning(
                f"[warn] orphan-pod delete failed for {pod_id!r}: "
                f"stdout={delete_result.stdout} stderr={delete_result.stderr}; "
                f"release manually with: runpodctl pod delete {pod_id}"
            )
        raise
    state_file = ctx.spec.resolved_state_file
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "pod_id": pod.pod_id,
                "gpu_id": gpu_id,
                "image": ctx.spec.pod.image,
                "datacenter_id": datacenter_id,
            },
            indent=2,
        )
    )
    return pod


def _wait_for_pod_ready(pod_id: str, *, gpu_id: str, timeout_sec: int = 900) -> PodConnection:
    """Wait until RunPod reports a pod as running with SSH host/port.

    Polls ``runpodctl pod get`` every 5 seconds until either the pod
    publishes a non-empty ``ssh.{ip, port}`` (returns the
    ``PodConnection``) or ``timeout_sec`` elapses (raises
    ``RuntimeError``). Emits a periodic INFO progress log every ~30 s
    after the wait crosses 60 s, so operators staring at a long
    cold-pull see status mid-wait instead of silent terminal.

    On timeout, the error message includes only ``desiredStatus``,
    ``ssh``, and ``uptimeSeconds`` from the last observed payload —
    the full pod-get payload would dump the env block (SSH pubkeys)
    and is rarely useful for diagnosis.
    """
    started_at = time.time()
    deadline = started_at + timeout_sec
    last_payload: dict[str, object] = {}
    next_progress_at = started_at + 60
    while True:
        now = time.time()
        if now >= deadline:
            break
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
            if now >= next_progress_at:
                elapsed = now - started_at
                logger.info(
                    f"[pod] {pod_id} waiting for SSH; T={elapsed:.0f}s "
                    f"status={status!r} ssh.error={ssh_info.get('error')!r} "
                    f"uptimeSeconds={payload.get('uptimeSeconds')!r}"
                )
                next_progress_at = now + 30
        time.sleep(5)
    trimmed = {k: last_payload.get(k) for k in ("desiredStatus", "ssh", "uptimeSeconds")}
    raise RuntimeError(f"pod {pod_id} did not become SSH-ready in {timeout_sec}s; last={trimmed}")


def try_resume_pod(
    state_file: Path,
    *,
    image: str,
    gpu_id: str,
    datacenter_id: str,
    ssh_ready_timeout_sec: int = 900,
) -> PodConnection | None:
    """Attempt to resume a paused pod from a previous ``recycle``-mode run.

    Reads ``state_file`` for a ``{pod_id, gpu_id, image, datacenter_id}``
    pointer. If the pod still exists in EXITED status AND the recorded
    ``image`` / ``gpu_id`` / ``datacenter_id`` all match the current
    spec, calls ``runpodctl pod start <pod_id>`` and returns a
    :class:`PodConnection` once the SSH proxy publishes a host/port.

    Returns ``None`` (so the caller can fall through to
    :func:`provision_pod`) in any of these cases:

    * State file missing or unreadable (no previous recycle to resume).
    * State file lacks required fields (older payload format).
    * ``runpodctl pod get`` reports the pod doesn't exist or isn't EXITED.
    * Drift detected (image/GPU/datacenter mismatch). In this case the
      stale pod is deleted via ``runpodctl pod delete`` before returning,
      so the next fresh-create doesn't compete with a leftover pod.

    Each fall-through path logs a WARNING explaining why so operators
    can diagnose "why didn't it resume?" without spelunking through code.
    """
    if not state_file.exists():
        return None
    try:
        payload = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[recycle] state file {state_file!s} unreadable ({exc}); fresh-creating")
        return None
    if not isinstance(payload, Mapping):
        logger.warning(
            f"[recycle] state file {state_file!s} has unexpected shape "
            f"({type(payload).__name__}); fresh-creating"
        )
        return None
    pod_id = str(payload.get("pod_id") or "")
    if not pod_id:
        logger.warning(f"[recycle] state file {state_file!s} has no pod_id; fresh-creating")
        return None
    stored_image = payload.get("image")
    stored_gpu_id = payload.get("gpu_id")
    stored_datacenter_id = payload.get("datacenter_id")
    if stored_image is None or stored_gpu_id is None or stored_datacenter_id is None:
        logger.warning(
            f"[recycle] state file {state_file!s} lacks image/gpu_id/datacenter_id "
            f"(pre-recycle format); fresh-creating"
        )
        return None
    argv_get = ["runpodctl", "pod", "get", pod_id, "-o", "json"]
    log_cmd(logger, "runpodctl", argv_get)
    get_result = subprocess.run(argv_get, capture_output=True, text=True, check=False)
    if get_result.returncode != 0:
        logger.warning(
            f"[recycle] pod {pod_id!r} not found "
            f"(runpodctl pod get rc={get_result.returncode}); "
            f"stale state file; fresh-creating"
        )
        return None
    try:
        pod_payload = json.loads(get_result.stdout)
    except json.JSONDecodeError:
        logger.warning(
            f"[recycle] runpodctl pod get returned non-JSON for {pod_id!r}; fresh-creating"
        )
        return None
    if not isinstance(pod_payload, Mapping):
        logger.warning(f"[recycle] pod-get payload for {pod_id!r} is not a dict; fresh-creating")
        return None
    desired_status = pod_payload.get("desiredStatus")
    if desired_status != "EXITED":
        logger.warning(
            f"[recycle] pod {pod_id!r} has desiredStatus={desired_status!r}, expected 'EXITED'; "
            f"fresh-creating (not deleting the pod — operator may be using it)"
        )
        return None
    drift = _detect_recycle_drift(
        stored_image=str(stored_image),
        stored_gpu_id=str(stored_gpu_id),
        stored_datacenter_id=str(stored_datacenter_id),
        current_image=image,
        current_gpu_id=gpu_id,
        current_datacenter_id=datacenter_id,
    )
    if drift:
        logger.warning(
            f"[recycle] drift detected for pod {pod_id!r}: {drift}; "
            f"deleting stale pod and fresh-creating"
        )
        argv_del = ["runpodctl", "pod", "delete", pod_id]
        log_cmd(logger, "runpodctl", argv_del)
        del_result = subprocess.run(argv_del, capture_output=True, text=True, check=False)
        if del_result.returncode != 0:
            logger.warning(
                f"[warn] failed to delete stale pod {pod_id!r}: "
                f"stdout={del_result.stdout} stderr={del_result.stderr}; "
                f"release manually with: runpodctl pod delete {pod_id}"
            )
        state_file.unlink(missing_ok=True)
        return None
    argv_start = ["runpodctl", "pod", "start", pod_id]
    log_cmd(logger, "runpodctl", argv_start)
    start_result = subprocess.run(argv_start, capture_output=True, text=True, check=False)
    if start_result.returncode != 0:
        logger.warning(
            f"[recycle] runpodctl pod start failed for {pod_id!r}: "
            f"stdout={start_result.stdout} stderr={start_result.stderr}; fresh-creating"
        )
        return None
    try:
        pod = _wait_for_pod_ready(pod_id, gpu_id=gpu_id, timeout_sec=ssh_ready_timeout_sec)
    except Exception as exc:
        logger.warning(
            f"[recycle] pod {pod_id!r} resumed but did not reach SSH-ready ({exc}); "
            f"deleting and fresh-creating"
        )
        argv_del = ["runpodctl", "pod", "delete", pod_id]
        log_cmd(logger, "runpodctl", argv_del)
        subprocess.run(argv_del, capture_output=True, text=True, check=False)
        state_file.unlink(missing_ok=True)
        return None
    logger.info(f"[lifecycle] pod {pod_id!r} resumed from recycle pointer at {state_file!s}")
    return pod


def _detect_recycle_drift(
    *,
    stored_image: str,
    stored_gpu_id: str,
    stored_datacenter_id: str,
    current_image: str,
    current_gpu_id: str,
    current_datacenter_id: str,
) -> str | None:
    """Return a human-readable drift summary, or ``None`` if compatible."""
    diffs: list[str] = []
    if stored_image != current_image:
        diffs.append(f"image: stored={stored_image!r} current={current_image!r}")
    if stored_gpu_id != current_gpu_id:
        diffs.append(f"gpu_id: stored={stored_gpu_id!r} current={current_gpu_id!r}")
    if stored_datacenter_id != current_datacenter_id:
        diffs.append(
            f"datacenter_id: stored={stored_datacenter_id!r} current={current_datacenter_id!r}"
        )
    if not diffs:
        return None
    return "; ".join(diffs)


@dataclass(frozen=True, slots=True)
class StalePod:
    """A RunPod pod in EXITED status that is still accruing volume storage."""

    pod_id: str
    name: str
    volume_in_gb: int
    age_hours: float | None
    estimated_daily_cost_usd: float


def cleanup_pod(
    pod_id: str,
    *,
    action: LifecycleAction,
    dry_run: bool,
    state_file: Path | None = None,
    volume_in_gb: int | None = None,
) -> None:
    """Take a lifecycle action on a pod after a run completes.

    Three actions:

    * ``"preserve"`` — leave the pod alone; compute and disk continue
      billing. Logs a WARNING with the manual-release command.
    * ``"stop"`` — issue ``runpodctl pod stop``; compute stops, **volume
      disk continues billing at ~$0.10/GB·month indefinitely** until
      released. Logs a multi-line actionable WARNING with estimated
      ``$/day`` cost (if ``volume_in_gb`` supplied) and the exact
      ``runpod-deploy cleanup`` command. State file is preserved so the
      operator can release the pod by name later.
    * ``"delete"`` — issue ``runpodctl pod delete``; compute stops and
      volume disk is released. State file is removed on success.

    The sentinel ``pod_id == "<pod-id>"`` (used by offline dry-runs)
    short-circuits all subprocess calls.

    Raises:
        ValueError: if ``action`` is not in
            :data:`runpod_deploy.config.LIFECYCLE_ACTIONS`.
    """
    if action == "preserve":
        logger.warning(
            f"[lifecycle] pod {pod_id!r} preserved "
            f"(compute + disk continue billing); "
            f"release manually with: runpodctl pod delete {pod_id}"
        )
        return

    if action == "stop":
        argv = ["runpodctl", "pod", "stop", pod_id]
        log_cmd(logger, "runpodctl", argv)
        if not (dry_run or pod_id == "<pod-id>"):
            result = subprocess.run(argv, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                logger.warning(
                    f"[warn] failed to stop pod {pod_id}: "
                    f"stdout={result.stdout} stderr={result.stderr}"
                )
                return
        _log_stop_cleanup_nudge(pod_id, state_file=state_file, volume_in_gb=volume_in_gb)
        return

    if action == "delete":
        argv = ["runpodctl", "pod", "delete", pod_id]
        log_cmd(logger, "runpodctl", argv)
        if dry_run or pod_id == "<pod-id>":
            return
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.warning(
                f"[warn] failed to delete pod {pod_id}: "
                f"stdout={result.stdout} stderr={result.stderr}"
            )
            return
        if state_file is not None:
            state_file.unlink(missing_ok=True)
        logger.info(f"[lifecycle] pod {pod_id!r} deleted; volume disk released")
        return

    if action == "recycle":
        argv = ["runpodctl", "pod", "stop", pod_id]
        log_cmd(logger, "runpodctl", argv)
        if dry_run or pod_id == "<pod-id>":
            return
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.warning(
                f"[warn] failed to recycle pod {pod_id}: "
                f"stdout={result.stdout} stderr={result.stderr}"
            )
            return
        # State file is intentionally preserved — it's the resume pointer the
        # next runpod-deploy run reads to find this pod.
        logger.info(f"[lifecycle] pod {pod_id!r} recycled (paused for reuse on next run)")
        return

    raise ValueError(
        f"cleanup_pod: unknown action {action!r}; "
        f"expected 'preserve', 'stop', 'delete', or 'recycle'"
    )


def _log_stop_cleanup_nudge(
    pod_id: str,
    *,
    state_file: Path | None,
    volume_in_gb: int | None,
) -> None:
    """Emit the multi-line WARNING that nudges the operator to clean up.

    This message is a regression-tested operator contract: it MUST
    contain the literal ``runpod-deploy cleanup --state-file`` command
    so the operator never has to remember the cleanup syntax after a
    failed run.
    """
    lines = [f"[lifecycle] pod {pod_id!r} stopped for forensics."]
    if volume_in_gb is not None and volume_in_gb > 0:
        daily = estimate_volume_storage_cost_usd_per_day(volume_in_gb)
        lines.append(
            f"  Volume disk ({volume_in_gb} GB) continues billing at "
            f"~${daily:.2f}/day (~${daily * 30:.2f}/mo) until released."
        )
    else:
        lines.append("  Volume disk continues billing until released.")
    lines.append("  When done investigating, release with:")
    if state_file is not None:
        lines.append(f"      runpod-deploy cleanup --state-file {state_file} --mode delete")
    else:
        lines.append(f"      runpodctl pod delete {pod_id}")
    lines.append("  Or audit all stale pods:")
    lines.append("      runpod-deploy ls-stale")
    logger.warning("\n".join(lines))


def list_stale_pods() -> list[StalePod]:
    """List every pod in EXITED status with its volume size and estimated daily cost.

    Shells out to ``runpodctl pod list -a --status EXITED -o json`` and
    parses the JSON array. Returns an empty list if no pods are stale.

    Raises:
        RuntimeError: if ``runpodctl`` exits non-zero or returns
            non-JSON output.
    """
    argv = ["runpodctl", "pod", "list", "--status", "EXITED", "-o", "json"]
    log_cmd(logger, "runpodctl", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"runpodctl pod list failed: stdout={result.stdout} stderr={result.stderr}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"runpodctl pod list returned non-JSON output: {result.stdout!r}"
        ) from exc
    if not isinstance(payload, list):
        raise RuntimeError(
            f"runpodctl pod list expected a JSON array, got {type(payload).__name__}"
        )
    out: list[StalePod] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            continue
        pod_id = str(raw.get("id") or "")
        if not pod_id:
            continue
        volume_in_gb = int(raw.get("volumeInGb") or 0)
        age_hours = _age_hours_from_uptime(raw.get("uptimeSeconds"))
        out.append(
            StalePod(
                pod_id=pod_id,
                name=str(raw.get("name") or ""),
                volume_in_gb=volume_in_gb,
                age_hours=age_hours,
                estimated_daily_cost_usd=estimate_volume_storage_cost_usd_per_day(volume_in_gb),
            )
        )
    return out


def _age_hours_from_uptime(value: Any) -> float | None:
    """Convert a ``uptimeSeconds`` field (int|None) to age in hours."""
    if value is None:
        return None
    try:
        return float(value) / 3600.0
    except (TypeError, ValueError):
        return None


def bulk_delete_pods(
    pod_ids: Sequence[str],
    *,
    dry_run: bool,
) -> list[tuple[str, bool, str]]:
    """Delete each pod in turn; collect failures rather than aborting on first.

    Returns a list of ``(pod_id, success, message)`` triples. ``message``
    is empty on success and contains stderr (truncated) on failure.

    The dry-run mode logs each ``runpodctl pod delete`` argv and returns
    success for all entries without invoking subprocess.
    """
    results: list[tuple[str, bool, str]] = []
    for pod_id in pod_ids:
        argv = ["runpodctl", "pod", "delete", pod_id]
        log_cmd(logger, "runpodctl", argv)
        if dry_run or pod_id == "<pod-id>":
            results.append((pod_id, True, ""))
            continue
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            results.append((pod_id, True, ""))
        else:
            msg = (result.stderr or result.stdout or "").strip()
            if len(msg) > 200:
                msg = msg[:200] + "…"
            logger.warning(f"[warn] failed to delete pod {pod_id}: {msg}")
            results.append((pod_id, False, msg))
    return results


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
