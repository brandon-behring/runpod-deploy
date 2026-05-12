"""Strict v1 YAML config loader for RunPod jobs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
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
    "SshSpec",
    "StopPolicySpec",
    "StorageSpec",
    "load_job_spec",
]

SCHEMA_VERSION = 1
STORAGE_NETWORK_VOLUME = "network_volume"
STORAGE_EPHEMERAL = "ephemeral"
DEFAULT_FAILURE_MARKERS = (
    "Traceback",
    "OutOfMemoryError",
    "CUDA out of memory",
    "No space left on device",
    "Killed",
)
_TEMPLATE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class LocalSpec:
    """Local repo paths used by a job config."""

    project_root: str = "."
    required_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PodSpec:
    """RunPod pod provisioning settings."""

    image: str
    datacenter_id: str
    gpu_order: tuple[str, ...]
    cloud_type: str = "SECURE"
    ports: tuple[str, ...] = ("22/tcp",)
    container_disk_gb: int = 20
    gpu_count: int = 1

    def __post_init__(self) -> None:
        if not self.image:
            raise ValueError("pod.image must be non-empty")
        if not self.datacenter_id:
            raise ValueError("pod.datacenter_id must be non-empty")
        if not self.gpu_order:
            raise ValueError("pod.gpu_order must contain at least one GPU id")
        if self.container_disk_gb <= 0:
            raise ValueError(f"pod.container_disk_gb must be > 0, got {self.container_disk_gb}")
        if self.gpu_count <= 0:
            raise ValueError(f"pod.gpu_count must be > 0, got {self.gpu_count}")


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
class StopPolicySpec:
    """Whether to stop the pod after success/failure."""

    on_success: bool = True
    on_failure: bool = True


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
    artifacts: tuple[ArtifactPullSpec, ...] = ()
    stop: StopPolicySpec = field(default_factory=StopPolicySpec)
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

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in self.variables:
                raise KeyError(f"unknown template variable {name!r} in {value!r}")
            return self.variables[name]

        return _TEMPLATE_RE.sub(replace, value)

    def render_path(self, value: str, *, base: Path | None = None) -> Path:
        """Render a local path; relative paths are resolved under `base`."""
        rendered = Path(self.render(value)).expanduser()
        if rendered.is_absolute():
            return rendered
        return (base or Path(self.variables["project_root"])) / rendered


def load_job_spec(path: Path | str) -> RunpodJobSpec:
    """Load a strict v1 YAML config."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    raw: Any = yaml.safe_load(config_path.read_text())
    if not isinstance(raw, Mapping):
        raise TypeError(f"YAML root must be a mapping, got {type(raw).__name__}")
    return _parse_job_spec(raw)


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
    project_root = _resolve_relative_path(spec.local.project_root, base=config_dir)
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
        variables[key] = _render_template(value, variables)
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


def _parse_job_spec(raw: Mapping[str, Any]) -> RunpodJobSpec:
    _check_keys(
        raw,
        "root",
        {
            "schema_version",
            "name",
            "run_id_prefix",
            "state_file",
            "local",
            "pod",
            "storage",
            "ssh",
            "budget",
            "remote_env",
            "setup",
            "preflight",
            "staging",
            "run",
            "artifacts",
            "stop",
            "variables",
        },
    )
    return RunpodJobSpec(
        schema_version=_as_int(raw.get("schema_version", SCHEMA_VERSION), "schema_version"),
        name=_as_str(raw.get("name"), "name"),
        run_id_prefix=_as_str(raw.get("run_id_prefix", raw.get("name")), "run_id_prefix"),
        state_file=_as_str(raw.get("state_file", "~/.runpod-deploy-current"), "state_file"),
        local=_parse_local(_mapping(raw.get("local", {}), "local")),
        pod=_parse_pod(_mapping(raw.get("pod"), "pod")),
        storage=_parse_storage(_mapping(raw.get("storage"), "storage")),
        ssh=_parse_ssh(_mapping(raw.get("ssh", {}), "ssh")),
        budget=_parse_budget(_mapping(raw.get("budget", {}), "budget")),
        remote_env=_parse_remote_env(_mapping(raw.get("remote_env", {}), "remote_env")),
        setup=_parse_commands(raw.get("setup", ()), "setup"),
        preflight=_parse_commands(raw.get("preflight", ()), "preflight"),
        staging=_parse_rsync_pushes(raw.get("staging", ())),
        run=_parse_run(_mapping(raw.get("run"), "run")),
        artifacts=_parse_artifacts(raw.get("artifacts", ())),
        stop=_parse_stop(_mapping(raw.get("stop", {}), "stop")),
        variables=_parse_str_dict(raw.get("variables", {}), "variables"),
    )


def _parse_local(raw: Mapping[str, Any]) -> LocalSpec:
    _check_keys(raw, "local", {"project_root", "required_paths"})
    return LocalSpec(
        project_root=_as_str(raw.get("project_root", "."), "local.project_root"),
        required_paths=_tuple_str(raw.get("required_paths", ()), "local.required_paths"),
    )


def _parse_pod(raw: Mapping[str, Any]) -> PodSpec:
    _check_keys(
        raw,
        "pod",
        {
            "image",
            "datacenter_id",
            "gpu_order",
            "cloud_type",
            "ports",
            "container_disk_gb",
            "gpu_count",
        },
    )
    return PodSpec(
        image=_as_str(raw.get("image"), "pod.image"),
        datacenter_id=_as_str(raw.get("datacenter_id"), "pod.datacenter_id"),
        gpu_order=_tuple_str(raw.get("gpu_order"), "pod.gpu_order"),
        cloud_type=_as_str(raw.get("cloud_type", "SECURE"), "pod.cloud_type"),
        ports=_tuple_str(raw.get("ports", ("22/tcp",)), "pod.ports"),
        container_disk_gb=_as_int(raw.get("container_disk_gb", 20), "pod.container_disk_gb"),
        gpu_count=_as_int(raw.get("gpu_count", 1), "pod.gpu_count"),
    )


def _parse_storage(raw: Mapping[str, Any]) -> StorageSpec:
    _check_keys(raw, "storage", {"mode", "volume_mount", "volume_name", "volume_gb"})
    return StorageSpec(
        mode=_as_str(raw.get("mode"), "storage.mode"),
        volume_mount=_as_str(raw.get("volume_mount", "/workspace"), "storage.volume_mount"),
        volume_name=_optional_str(raw.get("volume_name"), "storage.volume_name"),
        volume_gb=_optional_int(raw.get("volume_gb"), "storage.volume_gb"),
    )


def _parse_ssh(raw: Mapping[str, Any]) -> SshSpec:
    _check_keys(raw, "ssh", {"key_path"})
    return SshSpec(key_path=_as_str(raw.get("key_path", "~/.ssh/id_ed25519"), "ssh.key_path"))


def _parse_budget(raw: Mapping[str, Any]) -> BudgetSpec:
    _check_keys(
        raw,
        "budget",
        {"cost_cap_usd", "assumed_hourly_rate_usd", "max_runtime_minutes", "poll_interval_sec"},
    )
    return BudgetSpec(
        cost_cap_usd=_as_float(raw.get("cost_cap_usd", 10.0), "budget.cost_cap_usd"),
        assumed_hourly_rate_usd=_as_float(
            raw.get("assumed_hourly_rate_usd", 1.65),
            "budget.assumed_hourly_rate_usd",
        ),
        max_runtime_minutes=_optional_int(
            raw.get("max_runtime_minutes"),
            "budget.max_runtime_minutes",
        ),
        poll_interval_sec=_as_int(raw.get("poll_interval_sec", 60), "budget.poll_interval_sec"),
    )


def _parse_remote_env(raw: Mapping[str, Any]) -> RemoteEnvSpec:
    _check_keys(raw, "remote_env", {"source_files", "exports"})
    return RemoteEnvSpec(
        source_files=_tuple_str(raw.get("source_files", ()), "remote_env.source_files"),
        exports=_parse_str_dict(raw.get("exports", {}), "remote_env.exports"),
    )


def _parse_commands(raw: Any, label: str) -> tuple[CommandSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise TypeError(f"{label} must be a list of command mappings")
    out: list[CommandSpec] = []
    for i, item in enumerate(raw):
        item_label = f"{label}[{i}]"
        mapping = _mapping(item, item_label)
        _check_keys(mapping, item_label, {"command", "timeout_sec", "with_env"})
        out.append(
            CommandSpec(
                command=_as_str(mapping.get("command"), f"{item_label}.command"),
                timeout_sec=_as_int(mapping.get("timeout_sec", 600), f"{item_label}.timeout_sec"),
                with_env=_as_bool(mapping.get("with_env", False), f"{item_label}.with_env"),
            )
        )
    return tuple(out)


def _parse_rsync_pushes(raw: Any) -> tuple[RsyncPushSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise TypeError("staging must be a list of rsync push mappings")
    out: list[RsyncPushSpec] = []
    for i, item in enumerate(raw):
        item_label = f"staging[{i}]"
        mapping = _mapping(item, item_label)
        _check_keys(mapping, item_label, {"label", "source", "destination", "excludes", "delete"})
        out.append(
            RsyncPushSpec(
                label=_as_str(mapping.get("label"), f"{item_label}.label"),
                source=_as_str(mapping.get("source"), f"{item_label}.source"),
                destination=_as_str(mapping.get("destination"), f"{item_label}.destination"),
                excludes=_tuple_str(mapping.get("excludes", ()), f"{item_label}.excludes"),
                delete=_as_bool(mapping.get("delete", True), f"{item_label}.delete"),
            )
        )
    return tuple(out)


def _parse_run(raw: Mapping[str, Any]) -> RunSpec:
    _check_keys(
        raw, "run", {"script_path", "log_path", "success_marker", "failure_markers", "body"}
    )
    return RunSpec(
        script_path=_as_str(raw.get("script_path"), "run.script_path"),
        log_path=_as_str(raw.get("log_path"), "run.log_path"),
        success_marker=_as_str(raw.get("success_marker"), "run.success_marker"),
        failure_markers=_tuple_str(
            raw.get("failure_markers", DEFAULT_FAILURE_MARKERS),
            "run.failure_markers",
        ),
        body=_as_str(raw.get("body"), "run.body"),
    )


def _parse_artifacts(raw: Any) -> tuple[ArtifactPullSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise TypeError("artifacts must be a list of pull mappings")
    out: list[ArtifactPullSpec] = []
    for i, item in enumerate(raw):
        item_label = f"artifacts[{i}]"
        mapping = _mapping(item, item_label)
        _check_keys(
            mapping,
            item_label,
            {"label", "remote_path", "local_path", "required", "excludes", "delete"},
        )
        out.append(
            ArtifactPullSpec(
                label=_as_str(mapping.get("label"), f"{item_label}.label"),
                remote_path=_as_str(mapping.get("remote_path"), f"{item_label}.remote_path"),
                local_path=_as_str(mapping.get("local_path"), f"{item_label}.local_path"),
                required=_as_bool(mapping.get("required", True), f"{item_label}.required"),
                excludes=_tuple_str(mapping.get("excludes", ()), f"{item_label}.excludes"),
                delete=_as_bool(mapping.get("delete", True), f"{item_label}.delete"),
            )
        )
    return tuple(out)


def _parse_stop(raw: Mapping[str, Any]) -> StopPolicySpec:
    _check_keys(raw, "stop", {"on_success", "on_failure"})
    return StopPolicySpec(
        on_success=_as_bool(raw.get("on_success", True), "stop.on_success"),
        on_failure=_as_bool(raw.get("on_failure", True), "stop.on_failure"),
    )


def _check_keys(raw: Mapping[str, Any], label: str, allowed: set[str]) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise KeyError(
            f"unknown {label} keys: {sorted(unknown)}; expected subset of {sorted(allowed)}"
        )


def _mapping(raw: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(raw).__name__}")
    return raw


def _as_str(raw: Any, label: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(f"{label} must be str, got {type(raw).__name__}")
    return raw


def _optional_str(raw: Any, label: str) -> str | None:
    if raw is None:
        return None
    return _as_str(raw, label)


def _as_int(raw: Any, label: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise TypeError(f"{label} must be int, got {type(raw).__name__}")
    return raw


def _optional_int(raw: Any, label: str) -> int | None:
    if raw is None:
        return None
    return _as_int(raw, label)


def _as_float(raw: Any, label: str) -> float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise TypeError(f"{label} must be float, got {type(raw).__name__}")
    return float(raw)


def _as_bool(raw: Any, label: str) -> bool:
    if not isinstance(raw, bool):
        raise TypeError(f"{label} must be bool, got {type(raw).__name__}")
    return raw


def _tuple_str(raw: Any, label: str) -> tuple[str, ...]:
    if raw is None:
        raise TypeError(f"{label} must be a list of strings, got None")
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise TypeError(f"{label} must be a list of strings, got {type(raw).__name__}")
    out: list[str] = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise TypeError(f"{label}[{i}] must be str, got {type(item).__name__}")
        out.append(item)
    return tuple(out)


def _parse_str_dict(raw: Any, label: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(raw).__name__}")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise TypeError(f"{label} key must be str, got {type(key).__name__}")
        if not isinstance(value, str):
            raise TypeError(f"{label}[{key!r}] must be str, got {type(value).__name__}")
        out[key] = value
    return out


def _resolve_relative_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def _render_template(value: str, variables: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(f"unknown template variable {name!r} in {value!r}")
        return variables[name]

    return _TEMPLATE_RE.sub(replace, value)
