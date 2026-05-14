"""Strict v2 YAML config loader for RunPod jobs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "ArtifactPullSpec",
    "BudgetSpec",
    "CommandSpec",
    "JobContext",
    "LocalSpec",
    "PodSpec",
    "RemoteEnvSpec",
    "RsyncPushSpec",
    "RunSpec",
    "RunpodJobSpec",
    "SecretSpec",
    "SshSpec",
    "StopPolicySpec",
    "StorageSpec",
    "TelemetrySpec",
    "load_job_spec",
]

_OCTAL_MODE_RE = re.compile(r"^0?[0-7]{3}$")

SCHEMA_VERSION = 2
STORAGE_NETWORK_VOLUME = "network_volume"
STORAGE_EPHEMERAL = "ephemeral"
DEFAULT_FAILURE_MARKERS = (
    "Traceback",
    "OutOfMemoryError",
    "CUDA out of memory",
    "No space left on device",
    "Killed",
)


@dataclass(frozen=True, slots=True)
class LocalSpec:
    """Local repo paths used by a job config."""

    project_root: str = "."
    required_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PodSpec:
    """RunPod pod provisioning settings."""

    image: str
    datacenters: tuple[str, ...]
    gpu_order: tuple[str, ...]
    cloud_type: str = "SECURE"
    ports: tuple[str, ...] = ("22/tcp",)
    container_disk_gb: int = 20
    gpu_count: int = 1
    spot: bool = False
    min_vcpu_count: int | None = None
    min_memory_gb: int | None = None

    def __post_init__(self) -> None:
        if not self.image:
            raise ValueError("pod.image must be non-empty")
        if not self.datacenters:
            raise ValueError("pod.datacenters must contain at least one datacenter id")
        if not self.gpu_order:
            raise ValueError("pod.gpu_order must contain at least one GPU id")
        if self.container_disk_gb <= 0:
            raise ValueError(f"pod.container_disk_gb must be > 0, got {self.container_disk_gb}")
        if self.gpu_count <= 0:
            raise ValueError(f"pod.gpu_count must be > 0, got {self.gpu_count}")
        if self.min_vcpu_count is not None and self.min_vcpu_count <= 0:
            raise ValueError(f"pod.min_vcpu_count must be > 0, got {self.min_vcpu_count}")
        if self.min_memory_gb is not None and self.min_memory_gb <= 0:
            raise ValueError(f"pod.min_memory_gb must be > 0, got {self.min_memory_gb}")


@dataclass(frozen=True, slots=True)
class StorageSpec:
    """RunPod storage settings."""

    mode: str
    volume_mount: str = "/workspace"
    volume_name: str | None = None
    volume_gb: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in {STORAGE_NETWORK_VOLUME, STORAGE_EPHEMERAL}:
            raise ValueError(
                f"storage.mode must be 'network_volume' or 'ephemeral', got {self.mode!r}"
            )
        if not self.volume_mount.startswith("/"):
            raise ValueError(f"storage.volume_mount must be absolute, got {self.volume_mount!r}")
        if self.mode == STORAGE_NETWORK_VOLUME and not self.volume_name:
            raise ValueError("storage.volume_name is required for network_volume storage")
        if self.mode == STORAGE_EPHEMERAL and (self.volume_gb is None or self.volume_gb <= 0):
            raise ValueError("storage.volume_gb must be positive for ephemeral storage")


@dataclass(frozen=True, slots=True)
class SshSpec:
    """SSH settings for pod access."""

    key_path: str = "~/.ssh/id_ed25519"

    @property
    def resolved_key_path(self) -> Path:
        """Local SSH key path with `~` expanded."""
        return Path(self.key_path).expanduser()


@dataclass(frozen=True, slots=True)
class BudgetSpec:
    """Cost and monitoring limits."""

    cost_cap_usd: float = 10.0
    assumed_hourly_rate_usd: float = 1.65
    max_runtime_minutes: int | None = None
    poll_interval_sec: int = 60

    def __post_init__(self) -> None:
        if self.cost_cap_usd <= 0:
            raise ValueError(f"budget.cost_cap_usd must be > 0, got {self.cost_cap_usd}")
        if self.assumed_hourly_rate_usd <= 0:
            raise ValueError(
                "budget.assumed_hourly_rate_usd must be > 0, " f"got {self.assumed_hourly_rate_usd}"
            )
        if self.max_runtime_minutes is not None and self.max_runtime_minutes <= 0:
            raise ValueError(
                f"budget.max_runtime_minutes must be positive, got {self.max_runtime_minutes}"
            )
        if self.poll_interval_sec <= 0:
            raise ValueError(f"budget.poll_interval_sec must be > 0, got {self.poll_interval_sec}")

    @property
    def timeout_sec(self) -> int:
        """Runtime ceiling implied by max_runtime_minutes or the cost cap."""
        if self.max_runtime_minutes is not None:
            return self.max_runtime_minutes * 60
        return int((self.cost_cap_usd / self.assumed_hourly_rate_usd) * 3600)


@dataclass(frozen=True, slots=True)
class RemoteEnvSpec:
    """Remote environment sourced before selected commands."""

    source_files: tuple[str, ...] = ()
    exports: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One remote shell command."""

    command: str
    timeout_sec: int = 600
    with_env: bool = False

    def __post_init__(self) -> None:
        if not self.command.strip():
            raise ValueError("command.command must be non-empty")
        if self.timeout_sec <= 0:
            raise ValueError(f"command.timeout_sec must be > 0, got {self.timeout_sec}")


@dataclass(frozen=True, slots=True)
class RsyncPushSpec:
    """One local-to-remote rsync push."""

    label: str
    source: str
    destination: str
    excludes: tuple[str, ...] = ()
    delete: bool = True

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("staging.push[].label must be non-empty")
        if not self.source:
            raise ValueError(f"staging.push[{self.label!r}].source must be non-empty")
        if not self.destination:
            raise ValueError(f"staging.push[{self.label!r}].destination must be non-empty")


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Detached remote run script settings."""

    script_path: str
    log_path: str
    success_marker: str
    body: str
    failure_markers: tuple[str, ...] = DEFAULT_FAILURE_MARKERS

    def __post_init__(self) -> None:
        if not (self.script_path.startswith("/") or self.script_path.startswith("{")):
            raise ValueError(
                f"run.script_path must be absolute or a template, got {self.script_path!r}"
            )
        if not (self.log_path.startswith("/") or self.log_path.startswith("{")):
            raise ValueError(f"run.log_path must be absolute or a template, got {self.log_path!r}")
        if not self.success_marker:
            raise ValueError("run.success_marker must be non-empty")
        if not self.body.strip():
            raise ValueError("run.body must be non-empty")


@dataclass(frozen=True, slots=True)
class ArtifactPullSpec:
    """One remote-to-local artifact pull."""

    label: str
    remote_path: str
    local_path: str
    required: bool = True
    excludes: tuple[str, ...] = ()
    delete: bool = True

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("artifacts.pull[].label must be non-empty")
        if not self.remote_path:
            raise ValueError(f"artifacts.pull[{self.label!r}].remote_path must be non-empty")
        if not self.local_path:
            raise ValueError(f"artifacts.pull[{self.label!r}].local_path must be non-empty")


@dataclass(frozen=True, slots=True)
class SecretSpec:
    """One staged secret file on the pod.

    Exactly one of ``env`` or ``file`` must be set:

    - ``env``: a tuple of local environment variable names. The orchestrator
      reads each variable from the local process environment and writes
      ``KEY=value`` lines to ``destination`` on the pod.
    - ``file``: a local file path (with ``~`` expanded). The orchestrator copies
      the file to ``destination`` on the pod.

    ``mode`` is a 3- or 4-digit octal string (default ``"0600"``) enforced via
    rsync's ``--chmod=Fnnn`` flag on transfer.
    """

    name: str
    destination: str
    env: tuple[str, ...] = ()
    file: str | None = None
    mode: str = "0600"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("secrets[].name must be non-empty")
        if not self.destination:
            raise ValueError(f"secrets[{self.name!r}].destination must be non-empty")
        if not (self.destination.startswith("/") or self.destination.startswith("{")):
            raise ValueError(
                f"secrets[{self.name!r}].destination must be absolute or a template, "
                f"got {self.destination!r}"
            )
        if bool(self.env) == (self.file is not None):
            raise ValueError(
                f"secrets[{self.name!r}] must set exactly one of 'env' or 'file', "
                f"got env={self.env!r} file={self.file!r}"
            )
        for var in self.env:
            if not var.isidentifier():
                raise ValueError(
                    f"secrets[{self.name!r}].env must contain valid identifiers, got {var!r}"
                )
        if not _OCTAL_MODE_RE.match(self.mode):
            raise ValueError(
                f"secrets[{self.name!r}].mode must be a 3- or 4-digit octal string, "
                f"got {self.mode!r}"
            )


@dataclass(frozen=True, slots=True)
class StopPolicySpec:
    """Whether to stop the pod after success/failure."""

    on_success: bool = True
    on_failure: bool = True


@dataclass(frozen=True, slots=True)
class TelemetrySpec:
    """Pod-side telemetry capture knobs."""

    enabled: bool = True
    sample_interval_sec: int = 30
    capture_nvidia_smi: bool = True
    capture_dmesg: bool = True
    capture_pod_describe: bool = True
    capture_remote_env: bool = True
    capture_local_git: bool = True
    capture_payload_lockfile: bool = True

    def __post_init__(self) -> None:
        if self.sample_interval_sec < 5:
            raise ValueError(
                f"telemetry.sample_interval_sec must be >= 5, got {self.sample_interval_sec}"
            )


@dataclass(frozen=True, slots=True)
class RunpodJobSpec:
    """Complete single-job v1 config."""

    name: str
    pod: PodSpec
    storage: StorageSpec
    run: RunSpec
    schema_version: int = SCHEMA_VERSION
    run_id_prefix: str = ""
    state_file: str = "~/.runpod-deploy-current"
    local: LocalSpec = field(default_factory=LocalSpec)
    ssh: SshSpec = field(default_factory=SshSpec)
    budget: BudgetSpec = field(default_factory=BudgetSpec)
    remote_env: RemoteEnvSpec = field(default_factory=RemoteEnvSpec)
    setup: tuple[CommandSpec, ...] = ()
    preflight: tuple[CommandSpec, ...] = ()
    staging: tuple[RsyncPushSpec, ...] = ()
    secrets: tuple[SecretSpec, ...] = ()
    artifacts: tuple[ArtifactPullSpec, ...] = ()
    stop: StopPolicySpec = field(default_factory=StopPolicySpec)
    telemetry: TelemetrySpec = field(default_factory=TelemetrySpec)
    variables: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version!r}"
            )
        if not self.name:
            raise ValueError("name must be non-empty")
        if not self.run_id_prefix:
            object.__setattr__(self, "run_id_prefix", self.name)
        for key, value in self.variables.items():
            if not key.isidentifier():
                raise ValueError(f"variables key must be an identifier, got {key!r}")
            if not isinstance(value, str):
                raise TypeError(f"variables[{key!r}] must be str, got {type(value).__name__}")

    @property
    def resolved_state_file(self) -> Path:
        """Local state-file path with `~` expanded."""
        return Path(self.state_file).expanduser()


@dataclass(frozen=True, slots=True)
class JobContext:
    """Resolved config-path and template state for one invocation."""

    config_path: Path
    spec: RunpodJobSpec
    run_id: str
    run_dir: Path
    variables: dict[str, str]

    def render(self, value: str) -> str:
        """Render a config string using the job's variables."""
        return render_template(value, self.variables)

    def render_path(self, value: str, *, base: Path | None = None) -> Path:
        """Render a local path; relative paths are resolved under `base`."""
        rendered = Path(self.render(value)).expanduser()
        if rendered.is_absolute():
            return rendered
        return (base or Path(self.variables["project_root"])) / rendered


# Imported here, after the dataclass definitions, to break the circular
# dependency: _config_parsers needs the dataclass types at runtime to
# construct instances; by this point in the module they are bound, so
# Python's partial-module returned during the import cycle is sufficient.
from runpod_deploy._config_parsers import (  # noqa: E402
    parse_job_spec,
    render_template,
    resolve_relative_path,
)


def load_job_spec(path: Path | str) -> RunpodJobSpec:
    """Load a strict v1 YAML config."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    raw: Any = yaml.safe_load(config_path.read_text())
    if not isinstance(raw, Mapping):
        raise TypeError(f"YAML root must be a mapping, got {type(raw).__name__}")
    return parse_job_spec(raw)


def build_job_context(
    spec: RunpodJobSpec,
    config_path: Path | str,
    *,
    timestamp: datetime | None = None,
) -> JobContext:
    """Resolve template variables for one run."""
    config = Path(config_path).resolve()
    stamp = timestamp or datetime.now(UTC)
    run_id = stamp.strftime(f"{spec.run_id_prefix}-%Y%m%dT%H%M%SZ")
    config_dir = config.parent
    project_root = resolve_relative_path(spec.local.project_root, base=config_dir)
    if project_root == Path.home():
        raise ValueError(
            f"project_root resolved to $HOME ({project_root}); this would stage your entire "
            "home directory. Check local.project_root in the config — for a YAML that lives "
            "inside the consumer repo, the typical value is '../..' (one level up from "
            "configs/runpod/), not '../../..'."
        )
    run_dir = project_root / "artifacts" / "runpod" / stamp.strftime("%Y%m%dT%H%M%SZ")
    variables: dict[str, str] = {
        "config_dir": str(config_dir),
        "project_root": str(project_root),
        "run_dir": str(run_dir),
        "run_id": run_id,
        "job_name": spec.name,
        "volume_mount": spec.storage.volume_mount,
    }
    for key, value in spec.variables.items():
        variables[key] = render_template(value, variables)
    return JobContext(
        config_path=config,
        spec=spec,
        run_id=run_id,
        run_dir=run_dir,
        variables=variables,
    )


def validate_local_paths(ctx: JobContext) -> None:
    """Validate local required paths declared by the job."""
    project_root = Path(ctx.variables["project_root"])
    missing: list[str] = []
    for rel in ctx.spec.local.required_paths:
        path = ctx.render_path(rel, base=project_root)
        if not path.exists():
            missing.append(str(path))
    if missing:
        raise FileNotFoundError(f"required local paths are missing: {missing}")
