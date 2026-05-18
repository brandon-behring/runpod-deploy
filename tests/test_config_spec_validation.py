"""Parametrized validation tests for the *Spec dataclasses.

Pins the diagnostic-message contract for each `__post_init__` raise
path so that silent acceptance of an invalid spec — which surfaces deep
inside orchestration rather than at YAML-load time — fails CI here
instead.

Audit ref: docs/audits/code-quality-2026-05-18.md §D2 (#108).
"""

from __future__ import annotations

from typing import Any

import pytest

from runpod_deploy.config import (
    ArtifactPullSpec,
    BudgetSpec,
    CommandSpec,
    LifecyclePolicySpec,
    PodSpec,
    RsyncPushSpec,
    RunpodJobSpec,
    RunSpec,
    SecretSpec,
    StorageSpec,
    TelemetrySpec,
)


def _valid_pod_kwargs() -> dict[str, Any]:
    return {
        "image": "runpod/pytorch:2.4.0",
        "datacenters": ("EU-RO-1",),
        "gpu_order": ("NVIDIA A100-SXM4-80GB",),
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "override,match",
    [
        ({"image": ""}, "pod.image must be non-empty"),
        ({"datacenters": ()}, "pod.datacenters must contain at least one"),
        ({"gpu_order": ()}, "pod.gpu_order must contain at least one"),
        ({"container_disk_gb": 0}, "pod.container_disk_gb must be > 0"),
        ({"container_disk_gb": -10}, "pod.container_disk_gb must be > 0"),
        ({"gpu_count": 0}, "pod.gpu_count must be > 0"),
        ({"min_vcpu_count": 0}, "pod.min_vcpu_count must be > 0"),
        ({"min_memory_gb": 0}, "pod.min_memory_gb must be > 0"),
        ({"python_version": "3"}, "pod.python_version must match"),
        ({"python_version": "3.13.5a1"}, "pod.python_version must match"),
        ({"python_version": "py313"}, "pod.python_version must match"),
    ],
)
def test_pod_spec_rejects_invalid(override: dict[str, Any], match: str) -> None:
    kwargs = _valid_pod_kwargs() | override
    with pytest.raises(ValueError, match=match):
        PodSpec(**kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"mode": "unknown"}, "storage.mode must be"),
        ({"mode": "ephemeral", "volume_gb": 20, "volume_mount": "relative/path"}, "absolute"),
        ({"mode": "network_volume"}, "storage.volume_name is required"),
        ({"mode": "ephemeral"}, "storage.volume_gb must be positive"),
        ({"mode": "ephemeral", "volume_gb": 0}, "storage.volume_gb must be positive"),
    ],
)
def test_storage_spec_rejects_invalid(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        StorageSpec(**kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    "override,match",
    [
        ({"cost_cap_usd": 0}, "budget.cost_cap_usd must be > 0"),
        ({"cost_cap_usd": -1.0}, "budget.cost_cap_usd must be > 0"),
        ({"assumed_hourly_rate_usd": 0}, "budget.assumed_hourly_rate_usd must be > 0"),
        ({"max_runtime_minutes": 0}, "budget.max_runtime_minutes must be positive"),
        ({"poll_interval_sec": 0}, "budget.poll_interval_sec must be > 0"),
        ({"ssh_ready_timeout_sec": 0}, "budget.ssh_ready_timeout_sec must be > 0"),
    ],
)
def test_budget_spec_rejects_invalid(override: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        BudgetSpec(**override)


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"command": ""}, "command.command must be non-empty"),
        ({"command": "   "}, "command.command must be non-empty"),
        ({"command": "ls", "timeout_sec": 0}, "command.timeout_sec must be > 0"),
        ({"command": "ls", "timeout_sec": -1}, "command.timeout_sec must be > 0"),
    ],
)
def test_command_spec_rejects_invalid(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        CommandSpec(**kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"label": "", "source": "src", "destination": "dst"}, "label must be non-empty"),
        ({"label": "x", "source": "", "destination": "dst"}, "source must be non-empty"),
        ({"label": "x", "source": "src", "destination": ""}, "destination must be non-empty"),
    ],
)
def test_rsync_push_spec_rejects_invalid(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        RsyncPushSpec(**kwargs)


def _valid_run_kwargs() -> dict[str, Any]:
    return {
        "script_path": "/workspace/run.sh",
        "log_path": "/workspace/run.log",
        "success_marker": "[demo] DONE",
        "body": "echo hi",
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "override,match",
    [
        ({"script_path": "relative.sh"}, "run.script_path must be absolute or a template"),
        ({"log_path": "relative.log"}, "run.log_path must be absolute or a template"),
        ({"success_marker": ""}, "run.success_marker must be non-empty"),
        ({"body": "   "}, "run.body must be non-empty"),
    ],
)
def test_run_spec_rejects_invalid(override: dict[str, Any], match: str) -> None:
    kwargs = _valid_run_kwargs() | override
    with pytest.raises(ValueError, match=match):
        RunSpec(**kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"label": "", "remote_path": "r", "local_path": "l"}, "label must be non-empty"),
        ({"label": "x", "remote_path": "", "local_path": "l"}, "remote_path must be non-empty"),
        ({"label": "x", "remote_path": "r", "local_path": ""}, "local_path must be non-empty"),
    ],
)
def test_artifact_pull_spec_rejects_invalid(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ArtifactPullSpec(**kwargs)


def _valid_secret_kwargs() -> dict[str, Any]:
    return {"name": "s", "destination": "/workspace/secret", "env": ("API_KEY",)}


@pytest.mark.unit
@pytest.mark.parametrize(
    "override,match",
    [
        ({"name": ""}, r"secrets\[\]\.name must be non-empty"),
        ({"destination": ""}, "destination must be non-empty"),
        ({"destination": "relative/path"}, "must be absolute or a template"),
        ({"env": (), "file": None}, "must set exactly one of 'env' or 'file'"),
        (
            {"env": ("API_KEY",), "file": "/local/path"},
            "must set exactly one of 'env' or 'file'",
        ),
        ({"env": ("1bad_identifier",)}, "must contain valid identifiers"),
        ({"mode": "abc"}, "mode must be a 3- or 4-digit octal string"),
        ({"mode": "00000"}, "mode must be a 3- or 4-digit octal string"),
    ],
)
def test_secret_spec_rejects_invalid(override: dict[str, Any], match: str) -> None:
    kwargs = _valid_secret_kwargs() | override
    with pytest.raises(ValueError, match=match):
        SecretSpec(**kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"on_success": "bogus"}, "lifecycle.on_success must be one of"),
        ({"on_failure": "bogus"}, "lifecycle.on_failure must be one of"),
        ({"on_failure": "recycle"}, "lifecycle.on_failure cannot be 'recycle'"),
    ],
)
def test_lifecycle_policy_spec_rejects_invalid(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        LifecyclePolicySpec(**kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    "override,match",
    [
        ({"sample_interval_sec": 4}, "telemetry.sample_interval_sec must be >= 5"),
        ({"sample_interval_sec": 0}, "telemetry.sample_interval_sec must be >= 5"),
        ({"sample_interval_sec": -1}, "telemetry.sample_interval_sec must be >= 5"),
    ],
)
def test_telemetry_spec_rejects_invalid(override: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        TelemetrySpec(**override)


def _valid_runpod_job_spec_kwargs() -> dict[str, Any]:
    return {
        "name": "demo",
        "pod": PodSpec(**_valid_pod_kwargs()),
        "storage": StorageSpec(mode="ephemeral", volume_gb=20),
        "run": RunSpec(**_valid_run_kwargs()),
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "override,match,exc_type",
    [
        ({"schema_version": 1}, "schema_version must be 2", ValueError),
        ({"schema_version": 99}, "schema_version must be 2", ValueError),
        ({"name": ""}, "name must be non-empty", ValueError),
        (
            {"variables": {"1bad": "x"}},
            "variables key must be an identifier",
            ValueError,
        ),
        (
            {"variables": {"good": 42}},
            "must be str",
            TypeError,
        ),
    ],
)
def test_runpod_job_spec_rejects_invalid(
    override: dict[str, Any], match: str, exc_type: type[Exception]
) -> None:
    kwargs = _valid_runpod_job_spec_kwargs() | override
    with pytest.raises(exc_type, match=match):
        RunpodJobSpec(**kwargs)
