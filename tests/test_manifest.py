from __future__ import annotations

import json
from pathlib import Path

import pytest

from runpod_deploy.config import build_job_context, load_job_spec
from runpod_deploy.manifest import build_pull_manifest, write_pull_manifest
from runpod_deploy.provider import PodConnection


def _write_config_with_templated_artifacts(path: Path) -> Path:
    path.write_text("""
schema_version: 2
name: demo
run_id_prefix: demo
variables:
  smoke_dir: /workspace/{run_id}
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EU-RO-1]
  gpu_order:
    - NVIDIA A100-SXM4-80GB
storage:
  mode: network_volume
  volume_name: pid-workspace-100gb
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
artifacts:
  - label: gpu-info
    remote_path: "{smoke_dir}/gpu_info.txt"
    local_path: "{run_dir}"
    required: true
""")
    return path


@pytest.mark.unit
def test_write_pull_manifest_writes_json_with_resolved_paths(tmp_path: Path) -> None:
    config = _write_config_with_templated_artifacts(tmp_path / "job.yaml")
    spec = load_job_spec(config)
    ctx = build_job_context(spec, config)
    pod = PodConnection(pod_id="abc123", host="1.2.3.4", port=22, gpu_id="NVIDIA A100-SXM4-80GB")

    manifest_path = write_pull_manifest(ctx, failed=False, pod=pod)

    payload = json.loads(manifest_path.read_text())
    artifact = payload["artifacts"][0]
    assert "{" not in artifact["remote_path"]
    assert "{" not in artifact["local_path"]
    assert artifact["remote_path"].startswith("/workspace/demo-")
    assert artifact["remote_path"].endswith("/gpu_info.txt")
    assert artifact["local_path"] == str(ctx.run_dir)


@pytest.mark.unit
def test_build_pull_manifest_records_pod_metadata(tmp_path: Path) -> None:
    config = _write_config_with_templated_artifacts(tmp_path / "job.yaml")
    spec = load_job_spec(config)
    ctx = build_job_context(spec, config)
    pod = PodConnection(pod_id="abc123", host="1.2.3.4", port=22, gpu_id="NVIDIA A100-SXM4-80GB")

    manifest = build_pull_manifest(ctx, failed=False, pod=pod)

    assert manifest["pod_id"] == "abc123"
    assert manifest["gpu_id"] == "NVIDIA A100-SXM4-80GB"
    assert manifest["job_name"] == "demo"
    assert manifest["storage_mode"] == "network_volume"
    assert manifest["volume_name"] == "pid-workspace-100gb"
    assert manifest["failed"] is False


@pytest.mark.unit
def test_build_pull_manifest_handles_missing_pod(tmp_path: Path) -> None:
    config = _write_config_with_templated_artifacts(tmp_path / "job.yaml")
    spec = load_job_spec(config)
    ctx = build_job_context(spec, config)

    manifest = build_pull_manifest(ctx, failed=True, pod=None)

    assert manifest["pod_id"] is None
    assert manifest["gpu_id"] is None
    assert manifest["failed"] is True
