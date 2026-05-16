"""Config-driven RunPod orchestration."""

import logging

from runpod_deploy.config import (
    DEFAULT_STAGING_EXCLUDES,
    SCHEMA_VERSION,
    STORAGE_EPHEMERAL,
    STORAGE_NETWORK_VOLUME,
    ArtifactPullSpec,
    BudgetSpec,
    CommandSpec,
    JobContext,
    LocalSpec,
    PodSpec,
    RemoteEnvSpec,
    RsyncPushSpec,
    RunpodJobSpec,
    RunSpec,
    SecretSpec,
    SshSpec,
    StopPolicySpec,
    StorageSpec,
    TelemetrySpec,
    build_job_context,
    load_job_spec,
    validate_local_paths,
)
from runpod_deploy.metadata import capture_local_git, capture_payload_lockfile
from runpod_deploy.orchestrator import run_job
from runpod_deploy.pricing import GpuPrice, fetch_gpu_prices, select_price_for_pod
from runpod_deploy.provider import PodConnection, resolve_volume, select_gpu_across_datacenters
from runpod_deploy.transport import RemoteRunError, RemoteRunner, rsync_argv

__all__ = [
    "DEFAULT_STAGING_EXCLUDES",
    "SCHEMA_VERSION",
    "STORAGE_EPHEMERAL",
    "STORAGE_NETWORK_VOLUME",
    "ArtifactPullSpec",
    "BudgetSpec",
    "CommandSpec",
    "GpuPrice",
    "JobContext",
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
    "StopPolicySpec",
    "StorageSpec",
    "TelemetrySpec",
    "build_job_context",
    "capture_local_git",
    "capture_payload_lockfile",
    "fetch_gpu_prices",
    "load_job_spec",
    "resolve_volume",
    "rsync_argv",
    "run_job",
    "select_gpu_across_datacenters",
    "select_price_for_pod",
    "validate_local_paths",
]

__version__ = "0.7.8"

logging.getLogger(__name__).addHandler(logging.NullHandler())
