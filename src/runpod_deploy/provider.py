"""RunPod provider operations backed by `runpodctl`."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runpod_deploy.config import STORAGE_EPHEMERAL, STORAGE_NETWORK_VOLUME, JobContext
from runpod_deploy.transport import log_cmd

__all__ = [
    "PodConnection",
    "build_pod_create_argv",
    "resolve_volume",
    "run_json",
    "select_gpu_for_datacenter",
    "stop_pod",
    "wait_for_pod_ready",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PodConnection:
    """SSH-ready RunPod connection details."""

    pod_id: str
    host: str
    port: int
    gpu_id: str


def select_gpu_for_datacenter(
    datacenters: Sequence[dict[str, object]],
    *,
    datacenter_id: str,
    gpu_order: Sequence[str],
) -> str:
    """Select the first configured available GPU in a datacenter."""
    for dc in datacenters:
        if dc.get("id") != datacenter_id:
            continue
        availability = dc.get("gpuAvailability") or []
        if not isinstance(availability, list):
            break
        by_id = {
            str(item.get("gpuId")): str(item.get("stockStatus") or "").strip()
            for item in availability
            if isinstance(item, dict)
        }
        for gpu_id in gpu_order:
            stock = by_id.get(gpu_id, "")
            if stock and stock.lower() not in {"none", "unavailable", "out"}:
                return gpu_id
        raise RuntimeError(f"no configured GPU is available in {datacenter_id}; observed={by_id}")
    raise RuntimeError(f"datacenter {datacenter_id!r} not found in runpodctl datacenter list")


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


def build_pod_create_argv(ctx: JobContext, *, volume_id: str | None, gpu_id: str) -> list[str]:
    """Build the `runpodctl pod create` argv."""
    spec = ctx.spec
    argv = [
        "runpodctl",
        "pod",
        "create",
        "--gpu-id",
        gpu_id,
    ]
    if spec.pod.gpu_count > 1:
        argv.extend(["--gpu-count", str(spec.pod.gpu_count)])
    argv.extend(
        [
            "--image",
            spec.pod.image,
            "--data-center-ids",
            spec.pod.datacenter_id,
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
    dry_run: bool,
) -> PodConnection:
    """Provision a pod and return SSH connection details."""
    argv = build_pod_create_argv(ctx, volume_id=volume_id, gpu_id=gpu_id)
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
    pod = wait_for_pod_ready(pod_id, ctx, gpu_id=gpu_id)
    state_file = ctx.spec.resolved_state_file
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"pod_id": pod.pod_id, "gpu_id": gpu_id}, indent=2))
    return pod


def wait_for_pod_ready(pod_id: str, ctx: JobContext, *, gpu_id: str) -> PodConnection:
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
