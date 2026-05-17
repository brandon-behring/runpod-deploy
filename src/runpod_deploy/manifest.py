"""Manifest helpers for runpod-deploy artifact pulls (v2 schema)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runpod_deploy.config import ArtifactPullSpec, JobContext
from runpod_deploy.provider import PodConnection

__all__ = ["ArtifactResult", "build_pull_manifest", "write_pull_manifest"]

SCHEMA_VERSION = "v2"


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    """Outcome of one rsync_pull invocation. Result type, not YAML-parsed."""

    label: str
    status: str
    bytes_transferred: int | None = None
    duration_sec: float | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"success", "failed", "skipped"}:
            raise ValueError(
                f"ArtifactResult.status must be one of success|failed|skipped, "
                f"got {self.status!r}"
            )


def build_pull_manifest(
    ctx: JobContext,
    *,
    failed: bool,
    pod: PodConnection | None,
    datacenter_id: str | None = None,
    deploy_metadata: Mapping[str, object] | None = None,
    artifact_results: Sequence[ArtifactResult] = (),
    telemetry_files: Sequence[Path] = (),
    wall_time_sec: float | None = None,
    gpu_price_per_hour_usd: float | None = None,
    gpu_price_source: str | None = None,
    pod_final_state: str | None = None,
    pod_resumed: bool = False,
) -> dict[str, Any]:
    """Build a v2 JSON-serializable pull manifest.

    All v2-only fields are keyword-only with defaults so legacy callers
    (those that only know ``failed`` and ``pod``) continue to work and
    emit a manifest with ``null`` placeholders for the new fields.

    ``pod_resumed`` is ``True`` when this run reused a paused pod from
    a previous ``lifecycle.on_success: recycle`` cycle, ``False`` when
    the pod was freshly provisioned via ``runpodctl pod create``.
    """
    spec = ctx.spec
    by_label = {result.label: result for result in artifact_results}
    return {
        "schema_version": SCHEMA_VERSION,
        "pulled_at_utc": datetime.now(UTC).isoformat(),
        "failed": failed,
        "job_name": spec.name,
        "run_id": ctx.run_id,
        "config_path": str(ctx.config_path),
        "storage_mode": spec.storage.mode,
        "datacenter_id": datacenter_id if datacenter_id is not None else spec.pod.datacenters[0],
        "gpu_id": pod.gpu_id if pod is not None else None,
        "gpu_price_per_hour_usd": gpu_price_per_hour_usd,
        "gpu_price_source": gpu_price_source,
        "pod_id": pod.pod_id if pod is not None else None,
        "pod_final_state": pod_final_state,
        "pod_resumed": pod_resumed,
        "image": spec.pod.image,
        "cost_cap_usd": spec.budget.cost_cap_usd,
        "wall_time_sec": wall_time_sec,
        "estimated_cost_usd": _estimated_cost_usd(wall_time_sec, gpu_price_per_hour_usd),
        "volume_mount": spec.storage.volume_mount,
        "volume_name": spec.storage.volume_name,
        "volume_gb": spec.storage.volume_gb,
        "deploy_metadata": dict(deploy_metadata) if deploy_metadata is not None else {},
        "artifacts": [
            _render_artifact(ctx, artifact, by_label.get(artifact.label))
            for artifact in spec.artifacts
        ],
        "telemetry_files": [str(p.name) for p in telemetry_files],
    }


def _render_artifact(
    ctx: JobContext,
    artifact: ArtifactPullSpec,
    result: ArtifactResult | None,
) -> dict[str, Any]:
    rendered: dict[str, Any] = {
        "label": artifact.label,
        "remote_path": ctx.render(artifact.remote_path),
        "local_path": ctx.render(artifact.local_path),
        "required": artifact.required,
        "excludes": [ctx.render(pattern) for pattern in artifact.excludes],
        "delete": artifact.delete,
    }
    if result is not None:
        rendered["status"] = result.status
        rendered["bytes_transferred"] = result.bytes_transferred
        rendered["duration_sec"] = result.duration_sec
        if result.error is not None:
            rendered["error"] = result.error
    else:
        rendered["status"] = None
        rendered["bytes_transferred"] = None
        rendered["duration_sec"] = None
    return rendered


def _estimated_cost_usd(
    wall_time_sec: float | None, gpu_price_per_hour_usd: float | None
) -> float | None:
    if wall_time_sec is None or gpu_price_per_hour_usd is None:
        return None
    return round(gpu_price_per_hour_usd * wall_time_sec / 3600.0, 4)


def write_pull_manifest(
    ctx: JobContext,
    *,
    failed: bool,
    pod: PodConnection | None,
    filename: str = "runpod_deploy_pull_manifest.json",
    datacenter_id: str | None = None,
    deploy_metadata: Mapping[str, object] | None = None,
    artifact_results: Sequence[ArtifactResult] = (),
    telemetry_files: Sequence[Path] = (),
    wall_time_sec: float | None = None,
    gpu_price_per_hour_usd: float | None = None,
    gpu_price_source: str | None = None,
    pod_final_state: str | None = None,
    pod_resumed: bool = False,
) -> Path:
    """Write the pull manifest into the run directory."""
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.run_dir / filename
    payload = build_pull_manifest(
        ctx,
        failed=failed,
        pod=pod,
        datacenter_id=datacenter_id,
        deploy_metadata=deploy_metadata,
        artifact_results=artifact_results,
        telemetry_files=telemetry_files,
        wall_time_sec=wall_time_sec,
        gpu_price_per_hour_usd=gpu_price_per_hour_usd,
        gpu_price_source=gpu_price_source,
        pod_final_state=pod_final_state,
        pod_resumed=pod_resumed,
    )
    path.write_text(json.dumps(payload, indent=2))
    return path
