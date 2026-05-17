"""Config-driven RunPod orchestration."""

import logging

from runpod_deploy.config import (
    DEFAULT_STAGING_EXCLUDES,
    LIFECYCLE_ACTIONS,
    SCHEMA_VERSION,
    STORAGE_EPHEMERAL,
    STORAGE_NETWORK_VOLUME,
    ArtifactPullSpec,
    BudgetSpec,
    CommandSpec,
    JobContext,
    LifecycleAction,
    LifecyclePolicySpec,
    LocalSpec,
    PodSpec,
    RemoteEnvSpec,
    RsyncPushSpec,
    RunpodJobSpec,
    RunSpec,
    SecretSpec,
    SshSpec,
    StorageSpec,
    TelemetrySpec,
    build_job_context,
    load_job_spec,
    validate_local_paths,
)
from runpod_deploy.metadata import capture_local_git, capture_payload_lockfile
from runpod_deploy.orchestrator import run_job
from runpod_deploy.pricing import (
    VOLUME_STORAGE_USD_PER_GB_MONTH,
    GpuPrice,
    estimate_volume_storage_cost_usd_per_day,
    fetch_gpu_prices,
    select_price_for_pod,
)
from runpod_deploy.provider import (
    PodConnection,
    StalePod,
    bulk_delete_pods,
    cleanup_pod,
    list_stale_pods,
    resolve_volume,
    select_gpu_across_datacenters,
)
from runpod_deploy.transport import RemoteRunError, RemoteRunner, rsync_argv

__all__ = [
    "DEFAULT_STAGING_EXCLUDES",
    "LIFECYCLE_ACTIONS",
    "SCHEMA_VERSION",
    "STORAGE_EPHEMERAL",
    "STORAGE_NETWORK_VOLUME",
    "VOLUME_STORAGE_USD_PER_GB_MONTH",
    "ArtifactPullSpec",
    "BudgetSpec",
    "CommandSpec",
    "GpuPrice",
    "JobContext",
    "LifecycleAction",
    "LifecyclePolicySpec",
    "LocalSpec",
    "PodConnection",
    "PodSpec",
    "RemoteEnvSpec",
    "RemoteRunError",
    "RemoteRunner",
    "RsyncPushSpec",
    "RunSpec",
    "RunpodJobSpec",
    "SecretSpec",
    "SshSpec",
    "StalePod",
    "StorageSpec",
    "TelemetrySpec",
    "build_job_context",
    "bulk_delete_pods",
    "capture_local_git",
    "capture_payload_lockfile",
    "cleanup_pod",
    "estimate_volume_storage_cost_usd_per_day",
    "fetch_gpu_prices",
    "list_stale_pods",
    "load_job_spec",
    "resolve_volume",
    "rsync_argv",
    "run_job",
    "select_gpu_across_datacenters",
    "select_price_for_pod",
    "validate_local_paths",
]

__version__ = "0.8.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
