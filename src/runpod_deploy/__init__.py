"""Config-driven RunPod orchestration.

`runpod-deploy` is primarily a CLI tool — `runpod-deploy run --config
<yaml>` is the rev-rev surface, used by every known consumer today.
The Python API re-exported here is for the four use cases where
importing beats spawning a subprocess:

1. **Multi-manifest forensics** — analyzing past runs across many
   manifests. Use `walk_run_dirs`, `load_manifest`, `load_events`. See
   `docs/source/recipes/python-api-for-forensics.md`.
2. **Type-safe config construction / inspection** — programs building
   or inspecting `RunpodJobSpec` objects (e.g., dynamic sweeps that
   exceed what `--var KEY=VALUE` can express, or CI gates that assert
   on a loaded YAML). Use `load_job_spec` + the `*Spec` dataclasses.
3. **Cost-prediction tooling** — dashboards or CI gates estimating
   spend before any pod is provisioned. Use `fetch_gpu_prices` +
   `select_price_for_pod`.
4. **Embedded orchestration** — calling `run_job()` from a larger
   Python platform (e.g., a web UI's "Deploy" button or a multi-cloud
   orchestrator). Use `load_job_spec` + `run_job`.

For most use cases, prefer the CLI. See `docs/source/python-api-vs-cli.md`
for the full decision criterion.
"""

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
from runpod_deploy.forensics import load_events, load_manifest, walk_run_dirs
from runpod_deploy.metadata import capture_local_git, capture_payload_lockfile
from runpod_deploy.orchestrator import run_job
from runpod_deploy.preflight import (
    DatacenterInventory,
    InventoryReport,
    report_gpu_inventory,
)
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
    "DatacenterInventory",
    "GpuPrice",
    "InventoryReport",
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
    "load_events",
    "load_job_spec",
    "load_manifest",
    "report_gpu_inventory",
    "resolve_volume",
    "rsync_argv",
    "run_job",
    "select_gpu_across_datacenters",
    "select_price_for_pod",
    "validate_local_paths",
    "walk_run_dirs",
]

__version__ = "0.8.3"

logging.getLogger(__name__).addHandler(logging.NullHandler())
