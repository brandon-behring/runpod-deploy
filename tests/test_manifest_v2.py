from __future__ import annotations

import json
from pathlib import Path

import pytest

from runpod_deploy.config import build_job_context, load_job_spec
from runpod_deploy.manifest import (
    SCHEMA_VERSION,
    ArtifactResult,
    build_pull_manifest,
    write_pull_manifest,
)
from runpod_deploy.provider import PodConnection


def _write_config(path: Path) -> Path:
    path.write_text("""
schema_version: 2
name: demo
run_id_prefix: demo
pod:
  image: image
  datacenters: [US-MD-1, EU-RO-1]
  gpu_order: [g1]
storage:
  mode: ephemeral
  volume_gb: 50
run:
  script_path: /workspace/run.sh
  log_path: /workspace/run.log
  success_marker: DONE
  body: echo DONE
artifacts:
  - label: results
    remote_path: /workspace/out
    local_path: "{run_dir}/out"
""")
    return path


def _ctx(tmp_path: Path) -> tuple[Path, object]:
    config = _write_config(tmp_path / "job.yaml")
    return config, build_job_context(load_job_spec(config), config)


@pytest.mark.unit
def test_v2_manifest_emits_schema_version_v2(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)

    manifest = build_pull_manifest(ctx, failed=False, pod=None)

    assert manifest["schema_version"] == SCHEMA_VERSION == "v2"


@pytest.mark.unit
def test_v2_manifest_uses_explicit_datacenter_id_over_spec_default(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)

    manifest = build_pull_manifest(ctx, failed=False, pod=None, datacenter_id="EU-RO-1")

    assert manifest["datacenter_id"] == "EU-RO-1"  # second entry, not the spec default


@pytest.mark.unit
def test_v2_manifest_falls_back_to_first_datacenter_when_explicit_omitted(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)

    manifest = build_pull_manifest(ctx, failed=False, pod=None)

    assert manifest["datacenter_id"] == "US-MD-1"  # first entry of spec.pod.datacenters


@pytest.mark.unit
def test_v2_manifest_records_deploy_metadata(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)
    metadata = {
        "local_git_sha": "abc",
        "local_git_dirty": False,
        "local_git_branch": "main",
        "payload_lockfile": "uv.lock",
        "payload_lockfile_sha256": "def",
    }

    manifest = build_pull_manifest(ctx, failed=False, pod=None, deploy_metadata=metadata)

    assert manifest["deploy_metadata"] == metadata


@pytest.mark.unit
def test_v2_manifest_per_artifact_status_from_artifact_results(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)
    results = (
        ArtifactResult(
            label="results", status="success", bytes_transferred=1048576, duration_sec=3.2
        ),
    )

    manifest = build_pull_manifest(ctx, failed=False, pod=None, artifact_results=results)

    artifact = manifest["artifacts"][0]
    assert artifact["status"] == "success"
    assert artifact["bytes_transferred"] == 1048576
    assert artifact["duration_sec"] == 3.2
    assert "error" not in artifact


@pytest.mark.unit
def test_v2_manifest_artifact_failed_status_carries_error(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)
    results = (ArtifactResult(label="results", status="failed", error="rsync exit 23"),)

    manifest = build_pull_manifest(ctx, failed=True, pod=None, artifact_results=results)

    artifact = manifest["artifacts"][0]
    assert artifact["status"] == "failed"
    assert artifact["error"] == "rsync exit 23"


@pytest.mark.unit
def test_v2_manifest_artifact_status_null_when_no_results_supplied(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)

    manifest = build_pull_manifest(ctx, failed=False, pod=None)

    artifact = manifest["artifacts"][0]
    assert artifact["status"] is None
    assert artifact["bytes_transferred"] is None


@pytest.mark.unit
def test_v2_manifest_telemetry_files_emit_basenames_only(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)
    paths = (
        tmp_path / "nvidia_smi_start.txt",
        tmp_path / "events.jsonl",
        tmp_path / "metrics.jsonl",
    )

    manifest = build_pull_manifest(ctx, failed=False, pod=None, telemetry_files=paths)

    assert manifest["telemetry_files"] == [
        "nvidia_smi_start.txt",
        "events.jsonl",
        "metrics.jsonl",
    ]


@pytest.mark.unit
def test_v2_manifest_estimated_cost_from_wall_time_and_price(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)

    manifest = build_pull_manifest(
        ctx,
        failed=False,
        pod=None,
        wall_time_sec=1800.0,  # 30 min
        gpu_price_per_hour_usd=4.0,
    )

    assert manifest["wall_time_sec"] == 1800.0
    assert manifest["gpu_price_per_hour_usd"] == 4.0
    assert manifest["estimated_cost_usd"] == 2.0  # 30 min @ $4/hr


@pytest.mark.unit
def test_v2_manifest_estimated_cost_null_when_inputs_missing(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)

    manifest = build_pull_manifest(ctx, failed=False, pod=None, wall_time_sec=1800.0)

    assert manifest["estimated_cost_usd"] is None  # missing price


@pytest.mark.unit
def test_v2_manifest_records_pod_final_state_and_price_source(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)

    manifest = build_pull_manifest(
        ctx,
        failed=False,
        pod=None,
        gpu_price_source="pod_describe",
        pod_final_state="EXITED",
    )

    assert manifest["gpu_price_source"] == "pod_describe"
    assert manifest["pod_final_state"] == "EXITED"


@pytest.mark.unit
def test_v2_artifact_result_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="success|failed|skipped"):
        ArtifactResult(label="x", status="completed")


@pytest.mark.unit
def test_v2_write_pull_manifest_round_trips_to_disk(tmp_path: Path) -> None:
    _, ctx = _ctx(tmp_path)
    pod = PodConnection(pod_id="abc", host="1.2.3.4", port=22, gpu_id="g1")

    path = write_pull_manifest(
        ctx,
        failed=False,
        pod=pod,
        datacenter_id="US-MD-1",
        gpu_price_per_hour_usd=2.79,
        gpu_price_source="pod_describe",
        wall_time_sec=600.0,
        pod_final_state="EXITED",
    )

    payload = json.loads(path.read_text())
    assert payload["schema_version"] == "v2"
    assert payload["pod_id"] == "abc"
    assert payload["gpu_price_per_hour_usd"] == 2.79
