"""Internal YAML parsers for the runpod-deploy schema."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runpod_deploy.config import (
    DEFAULT_FAILURE_MARKERS,
    LIFECYCLE_ACTIONS,
    SCHEMA_VERSION,
    ArtifactPullSpec,
    BudgetSpec,
    CommandSpec,
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
)

logger = logging.getLogger(__name__)

__all__ = [
    "parse_job_spec",
    "render_template",
    "resolve_relative_path",
]

_TEMPLATE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def parse_job_spec(raw: Mapping[str, Any]) -> RunpodJobSpec:
    """Parse a validated YAML mapping into a RunpodJobSpec."""
    if "stop" in raw:
        raise ValueError(
            "the legacy 'stop' block was removed in v0.8.3; use the 'lifecycle' "
            "block with values preserve|stop|delete. See docs/source/migration-v3.md."
        )
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
            "secrets",
            "run",
            "artifacts",
            "lifecycle",
            "telemetry",
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
        secrets=_parse_secrets(raw.get("secrets", ())),
        run=_parse_run(_mapping(raw.get("run"), "run")),
        artifacts=_parse_artifacts(raw.get("artifacts", ())),
        lifecycle=_parse_lifecycle(raw),
        telemetry=_parse_telemetry(_mapping(raw.get("telemetry", {}), "telemetry")),
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
            "datacenters",
            "gpu_order",
            "cloud_type",
            "ports",
            "container_disk_gb",
            "gpu_count",
            "spot",
            "min_vcpu_count",
            "min_memory_gb",
            "python_version",
        },
    )
    return PodSpec(
        image=_as_str(raw.get("image"), "pod.image"),
        datacenters=_tuple_str(raw.get("datacenters"), "pod.datacenters"),
        gpu_order=_tuple_str(raw.get("gpu_order"), "pod.gpu_order"),
        cloud_type=_as_str(raw.get("cloud_type", "SECURE"), "pod.cloud_type"),
        ports=_tuple_str(raw.get("ports", ("22/tcp",)), "pod.ports"),
        container_disk_gb=_as_int(raw.get("container_disk_gb", 20), "pod.container_disk_gb"),
        gpu_count=_as_int(raw.get("gpu_count", 1), "pod.gpu_count"),
        spot=_as_bool(raw.get("spot", False), "pod.spot"),
        min_vcpu_count=_optional_int(raw.get("min_vcpu_count"), "pod.min_vcpu_count"),
        min_memory_gb=_optional_int(raw.get("min_memory_gb"), "pod.min_memory_gb"),
        python_version=_optional_str(raw.get("python_version"), "pod.python_version"),
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
        {
            "cost_cap_usd",
            "assumed_hourly_rate_usd",
            "max_runtime_minutes",
            "poll_interval_sec",
            "ssh_ready_timeout_sec",
        },
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
        ssh_ready_timeout_sec=_as_int(
            raw.get("ssh_ready_timeout_sec", 900),
            "budget.ssh_ready_timeout_sec",
        ),
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
    allowed = {
        "label",
        "source",
        "destination",
        "excludes",
        "delete",
        "excludes_default",
        "excludes_extra",
    }
    for i, item in enumerate(raw):
        item_label = f"staging[{i}]"
        mapping = _mapping(item, item_label)
        _check_keys(mapping, item_label, allowed)
        out.append(
            RsyncPushSpec(
                label=_as_str(mapping.get("label"), f"{item_label}.label"),
                source=_as_str(mapping.get("source"), f"{item_label}.source"),
                destination=_as_str(mapping.get("destination"), f"{item_label}.destination"),
                excludes=_tuple_str(mapping.get("excludes", ()), f"{item_label}.excludes"),
                delete=_as_bool(mapping.get("delete", True), f"{item_label}.delete"),
                excludes_default=_as_bool(
                    mapping.get("excludes_default", False),
                    f"{item_label}.excludes_default",
                ),
                excludes_extra=_tuple_str(
                    mapping.get("excludes_extra", ()),
                    f"{item_label}.excludes_extra",
                ),
            )
        )
    return tuple(out)


def _parse_secrets(raw: Any) -> tuple[SecretSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise TypeError("secrets must be a list of secret mappings")
    out: list[SecretSpec] = []
    for i, item in enumerate(raw):
        item_label = f"secrets[{i}]"
        mapping = _mapping(item, item_label)
        _check_keys(mapping, item_label, {"name", "destination", "env", "file", "mode"})
        out.append(
            SecretSpec(
                name=_as_str(mapping.get("name"), f"{item_label}.name"),
                destination=_as_str(mapping.get("destination"), f"{item_label}.destination"),
                env=_tuple_str(mapping.get("env", ()), f"{item_label}.env"),
                file=_optional_str(mapping.get("file"), f"{item_label}.file"),
                mode=_as_str(mapping.get("mode", "0600"), f"{item_label}.mode"),
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


def _parse_lifecycle(root: Mapping[str, Any]) -> LifecyclePolicySpec:
    """Parse the lifecycle policy from the root config.

    Raises:
        ValueError: if a value is not in :data:`LIFECYCLE_ACTIONS`.
    """
    if "lifecycle" in root:
        raw = _mapping(root.get("lifecycle", {}), "lifecycle")
        _check_keys(raw, "lifecycle", {"on_success", "on_failure"})
        return LifecyclePolicySpec(
            on_success=_parse_lifecycle_action(
                raw.get("on_success", "delete"), "lifecycle.on_success"
            ),
            on_failure=_parse_lifecycle_action(
                raw.get("on_failure", "stop"), "lifecycle.on_failure"
            ),
        )
    return LifecyclePolicySpec()


def _parse_lifecycle_action(value: Any, label: str) -> LifecycleAction:
    """Validate a ``lifecycle.*`` field as one of :data:`LIFECYCLE_ACTIONS`."""
    if not isinstance(value, str):
        raise TypeError(
            f"{label} must be a string in {LIFECYCLE_ACTIONS}, "
            f"got {type(value).__name__} ({value!r})"
        )
    if value not in LIFECYCLE_ACTIONS:
        raise ValueError(f"{label} must be one of {LIFECYCLE_ACTIONS}, got {value!r}")
    return value


def _parse_telemetry(raw: Mapping[str, Any]) -> TelemetrySpec:
    _check_keys(
        raw,
        "telemetry",
        {
            "enabled",
            "sample_interval_sec",
            "capture_nvidia_smi",
            "capture_dmesg",
            "capture_pod_describe",
            "capture_remote_env",
            "capture_local_git",
            "capture_payload_lockfile",
        },
    )
    return TelemetrySpec(
        enabled=_as_bool(raw.get("enabled", True), "telemetry.enabled"),
        sample_interval_sec=_as_int(
            raw.get("sample_interval_sec", 30), "telemetry.sample_interval_sec"
        ),
        capture_nvidia_smi=_as_bool(
            raw.get("capture_nvidia_smi", True), "telemetry.capture_nvidia_smi"
        ),
        capture_dmesg=_as_bool(raw.get("capture_dmesg", True), "telemetry.capture_dmesg"),
        capture_pod_describe=_as_bool(
            raw.get("capture_pod_describe", True), "telemetry.capture_pod_describe"
        ),
        capture_remote_env=_as_bool(
            raw.get("capture_remote_env", True), "telemetry.capture_remote_env"
        ),
        capture_local_git=_as_bool(
            raw.get("capture_local_git", True), "telemetry.capture_local_git"
        ),
        capture_payload_lockfile=_as_bool(
            raw.get("capture_payload_lockfile", True), "telemetry.capture_payload_lockfile"
        ),
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


def resolve_relative_path(value: str, *, base: Path) -> Path:
    """Resolve a possibly-relative path against ``base`` and absolutize it."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def render_template(value: str, variables: Mapping[str, str]) -> str:
    """Substitute ``{name}`` placeholders against ``variables``."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(f"unknown template variable {name!r} in {value!r}")
        return variables[name]

    return _TEMPLATE_RE.sub(replace, value)
