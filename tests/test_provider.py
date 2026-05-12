from __future__ import annotations

from pathlib import Path

import pytest

from runpod_deploy.config import build_job_context, load_job_spec
from runpod_deploy.provider import build_pod_create_argv, resolve_volume, select_gpu_for_datacenter


@pytest.mark.unit
def test_select_gpu_uses_first_available_gpu_in_order() -> None:
    gpu = select_gpu_for_datacenter(
        [
            {
                "id": "EU-RO-1",
                "gpuAvailability": [
                    {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": ""},
                    {"gpuId": "NVIDIA A100 80GB PCIe", "stockStatus": "Low"},
                ],
            }
        ],
        datacenter_id="EU-RO-1",
        gpu_order=("NVIDIA A100-SXM4-80GB", "NVIDIA A100 80GB PCIe"),
    )

    assert gpu == "NVIDIA A100 80GB PCIe"


@pytest.mark.unit
def test_select_gpu_fails_closed_on_unconfigured_available_gpu() -> None:
    with pytest.raises(RuntimeError, match="no configured GPU"):
        select_gpu_for_datacenter(
            [
                {
                    "id": "US-MD-1",
                    "gpuAvailability": [{"gpuId": "NVIDIA B200", "stockStatus": "High"}],
                }
            ],
            datacenter_id="US-MD-1",
            gpu_order=("NVIDIA A100-SXM4-80GB",),
        )


@pytest.mark.unit
def test_resolve_volume_enforces_datacenter() -> None:
    with pytest.raises(RuntimeError, match="expected EU-RO-1"):
        resolve_volume(
            [{"name": "pid-workspace-100gb", "id": "vol-1", "dataCenterId": "US-OR-1"}],
            volume_name="pid-workspace-100gb",
            expected_datacenter_id="EU-RO-1",
        )


@pytest.mark.unit
def test_pod_create_omits_gpu_count_for_single_gpu(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 1
name: demo
pod:
  image: image
  datacenter_id: EU-RO-1
  gpu_order: ["gpu-a"]
storage:
  mode: network_volume
  volume_name: pid-workspace-100gb
run:
  script_path: /workspace/run.sh
  log_path: /workspace/run.log
  success_marker: DONE
  body: echo DONE
""")
    ctx = build_job_context(load_job_spec(config), config)

    argv = build_pod_create_argv(ctx, volume_id="vol-1", gpu_id="gpu-a")

    assert "--gpu-count" not in argv
    assert "--ports" in argv
    assert "22/tcp" in argv
    assert "--network-volume-id" in argv


@pytest.mark.unit
def test_pod_create_uses_ephemeral_volume_gb(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 1
name: demo
pod:
  image: image
  datacenter_id: US-MD-1
  gpu_order: ["gpu-a"]
  gpu_count: 2
storage:
  mode: ephemeral
  volume_gb: 200
run:
  script_path: /workspace/run.sh
  log_path: /workspace/run.log
  success_marker: DONE
  body: echo DONE
""")
    ctx = build_job_context(load_job_spec(config), config)

    argv = build_pod_create_argv(ctx, volume_id=None, gpu_id="gpu-a")

    assert "--gpu-count" in argv
    assert "--volume-in-gb" in argv
    assert "200" in argv
    assert "--network-volume-id" not in argv
