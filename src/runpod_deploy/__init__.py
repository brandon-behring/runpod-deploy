"""Config-driven RunPod orchestration."""

import logging

from runpod_deploy.config import (
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
    SshSpec,
    StopPolicySpec,
    StorageSpec,
    TelemetrySpec,
    load_job_spec,
)
from runpod_deploy.metadata import capture_local_git, capture_payload_lockfile
from runpod_deploy.orchestrator import run_job
from runpod_deploy.pricing import GpuPrice, fetch_gpu_prices, select_price_for_pod
from runpod_deploy.provider import PodConnection, resolve_volume, select_gpu_across_datacenters
from runpod_deploy.transport import RemoteRunError, RemoteRunner, rsync_argv

__all__ = [
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
    "SshSpec",
    "StopPolicySpec",
    "StorageSpec",
    "TelemetrySpec",
    "capture_local_git",
    "capture_payload_lockfile",
    "fetch_gpu_prices",
    "load_job_spec",
    "resolve_volume",
    "rsync_argv",
    "run_job",
    "select_gpu_across_datacenters",
    "select_price_for_pod",
]

__version__ = "0.3.1"

logging.getLogger(__name__).addHandler(logging.NullHandler())
