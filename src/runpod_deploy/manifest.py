"""Manifest helpers for runpod-deploy artifact pulls."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runpod_deploy.config import ArtifactPullSpec, JobContext
from runpod_deploy.provider import PodConnection

__all__ = ["build_pull_manifest", "write_pull_manifest"]


def build_pull_manifest(
    ctx: JobContext,
    *,
    failed: bool,
    pod: PodConnection | None,
) -> dict[str, Any]:
    """Build a JSON-serializable pull manifest."""
    return {
        "schema_version": "v1",
        "pulled_at_utc": datetime.now(UTC).isoformat(),
        "failed": failed,
        "job_name": ctx.spec.name,
        "run_id": ctx.run_id,
        "config_path": str(ctx.config_path),
        "storage_mode": ctx.spec.storage.mode,
        "datacenter_id": ctx.spec.pod.datacenter_id,
        "gpu_id": pod.gpu_id if pod is not None else None,
        "pod_id": pod.pod_id if pod is not None else None,
        "image": ctx.spec.pod.image,
        "cost_cap_usd": ctx.spec.budget.cost_cap_usd,
        "volume_mount": ctx.spec.storage.volume_mount,
        "volume_name": ctx.spec.storage.volume_name,
        "volume_gb": ctx.spec.storage.volume_gb,
        "artifacts": [_render_artifact(ctx, artifact) for artifact in ctx.spec.artifacts],
    }


def _render_artifact(ctx: JobContext, artifact: ArtifactPullSpec) -> dict[str, Any]:
    return {
        "label": artifact.label,
        "remote_path": ctx.render(artifact.remote_path),
        "local_path": ctx.render(artifact.local_path),
        "required": artifact.required,
        "excludes": [ctx.render(pattern) for pattern in artifact.excludes],
        "delete": artifact.delete,
    }


def write_pull_manifest(
    ctx: JobContext,
    *,
    failed: bool,
    pod: PodConnection | None,
    filename: str = "runpod_deploy_pull_manifest.json",
) -> Path:
    """Write the pull manifest into the run directory."""
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.run_dir / filename
    path.write_text(json.dumps(build_pull_manifest(ctx, failed=failed, pod=pod), indent=2))
    return path
