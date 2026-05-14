from __future__ import annotations

from pathlib import Path

import pytest

from runpod_deploy.config import build_job_context, load_job_spec
from runpod_deploy.provider import (
    _build_pod_create_argv,
    resolve_volume,
    select_gpu_across_datacenters,
)


@pytest.mark.unit
def test_select_gpu_uses_first_available_gpu_in_order() -> None:
    gpu_id, dc_id = select_gpu_across_datacenters(
        [
            {
                "id": "EU-RO-1",
                "gpuAvailability": [
                    {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": ""},
                    {"gpuId": "NVIDIA A100 80GB PCIe", "stockStatus": "Low"},
                ],
            }
        ],
        datacenters=("EU-RO-1",),
        gpu_order=("NVIDIA A100-SXM4-80GB", "NVIDIA A100 80GB PCIe"),
    )

    assert gpu_id == "NVIDIA A100 80GB PCIe"
    assert dc_id == "EU-RO-1"


@pytest.mark.unit
def test_select_gpu_fails_closed_on_unconfigured_available_gpu() -> None:
    with pytest.raises(RuntimeError, match="no configured GPU available"):
        select_gpu_across_datacenters(
            [
                {
                    "id": "US-MD-1",
                    "gpuAvailability": [{"gpuId": "NVIDIA B200", "stockStatus": "High"}],
                }
            ],
            datacenters=("US-MD-1",),
            gpu_order=("NVIDIA A100-SXM4-80GB",),
        )


@pytest.mark.unit
def test_select_gpu_error_lists_observed_availability_per_dc() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        select_gpu_across_datacenters(
            [
                {
                    "id": "US-MD-1",
                    "gpuAvailability": [
                        {"gpuId": "NVIDIA H100 80GB HBM3", "stockStatus": "Medium"},
                        {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": "Low"},
                        {"gpuId": "NVIDIA H200 NVL", "stockStatus": ""},
                    ],
                }
            ],
            datacenters=("US-MD-1",),
            gpu_order=("NVIDIA H100 PCIe",),
        )

    msg = str(excinfo.value)
    assert "observed availability" in msg
    assert "NVIDIA H100 80GB HBM3 (Medium)" in msg
    assert "NVIDIA A100-SXM4-80GB (Low)" in msg
    # Empty stockStatus → not in tier_rank → omitted from observed lines.
    assert "H200 NVL" not in msg
    # Medium-tier should be listed before Low-tier.
    assert msg.index("Medium") < msg.index("Low")


@pytest.mark.unit
def test_select_gpu_fails_over_to_next_dc_when_first_is_out() -> None:
    failover_calls: list[tuple[str, str | None, str]] = []

    gpu_id, dc_id = select_gpu_across_datacenters(
        [
            {
                "id": "EUR-NO-2",
                "gpuAvailability": [{"gpuId": "NVIDIA H100 80GB HBM3", "stockStatus": "Out"}],
            },
            {
                "id": "US-GA-2",
                "gpuAvailability": [{"gpuId": "NVIDIA H100 80GB HBM3", "stockStatus": "High"}],
            },
        ],
        datacenters=("EUR-NO-2", "US-GA-2"),
        gpu_order=("NVIDIA H100 80GB HBM3",),
        on_failover=lambda failed, nxt, reason: failover_calls.append((failed, nxt, reason)),
    )

    assert (gpu_id, dc_id) == ("NVIDIA H100 80GB HBM3", "US-GA-2")
    assert len(failover_calls) == 1
    assert failover_calls[0][0] == "EUR-NO-2"
    assert failover_calls[0][1] == "US-GA-2"
    assert "no configured GPU available" in failover_calls[0][2]


@pytest.mark.unit
def test_select_gpu_skips_missing_dc_with_failover_callback() -> None:
    failover_calls: list[tuple[str, str | None, str]] = []

    gpu_id, dc_id = select_gpu_across_datacenters(
        [
            {
                "id": "US-GA-2",
                "gpuAvailability": [{"gpuId": "g1", "stockStatus": "Low"}],
            }
        ],
        datacenters=("EUR-NO-2", "US-GA-2"),
        gpu_order=("g1",),
        on_failover=lambda failed, nxt, reason: failover_calls.append((failed, nxt, reason)),
    )

    assert (gpu_id, dc_id) == ("g1", "US-GA-2")
    assert failover_calls[0][0] == "EUR-NO-2"
    assert "not found" in failover_calls[0][2]


@pytest.mark.unit
def test_select_gpu_raises_when_all_dcs_exhausted_lists_each() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        select_gpu_across_datacenters(
            [
                {"id": "DC-A", "gpuAvailability": [{"gpuId": "g1", "stockStatus": "Out"}]},
                {"id": "DC-B", "gpuAvailability": [{"gpuId": "g1", "stockStatus": "Out"}]},
            ],
            datacenters=("DC-A", "DC-B"),
            gpu_order=("g1",),
        )

    msg = str(excinfo.value)
    assert "no configured GPU available across datacenters ['DC-A', 'DC-B']" in msg


@pytest.mark.unit
def test_select_gpu_requires_non_empty_datacenters() -> None:
    with pytest.raises(ValueError, match="at least one"):
        select_gpu_across_datacenters([], datacenters=(), gpu_order=("g1",))


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
schema_version: 2
name: demo
pod:
  image: image
  datacenters: [EU-RO-1]
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

    argv = _build_pod_create_argv(ctx, volume_id="vol-1", gpu_id="gpu-a", datacenter_id="EU-RO-1")

    assert "--gpu-count" not in argv
    assert "--ports" in argv
    assert "22/tcp" in argv
    assert "--network-volume-id" in argv
    assert "--data-center-ids" in argv
    assert "EU-RO-1" in argv


@pytest.mark.unit
def test_pod_create_uses_ephemeral_volume_gb(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: demo
pod:
  image: image
  datacenters: [US-MD-1]
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

    argv = _build_pod_create_argv(ctx, volume_id=None, gpu_id="gpu-a", datacenter_id="US-MD-1")

    assert "--gpu-count" in argv
    assert "--volume-in-gb" in argv
    assert "200" in argv
    assert "--network-volume-id" not in argv


@pytest.mark.unit
def test_pod_create_emits_spot_and_min_resources_when_set(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: demo
pod:
  image: image
  datacenters: [EU-RO-1]
  gpu_order: ["gpu-a"]
  spot: true
  min_vcpu_count: 16
  min_memory_gb: 64
storage:
  mode: ephemeral
  volume_gb: 100
run:
  script_path: /workspace/run.sh
  log_path: /workspace/run.log
  success_marker: DONE
  body: echo DONE
""")
    ctx = build_job_context(load_job_spec(config), config)

    argv = _build_pod_create_argv(ctx, volume_id=None, gpu_id="gpu-a", datacenter_id="EU-RO-1")

    assert "--spot" in argv
    assert "--min-vcpu-count" in argv
    assert "16" in argv
    assert "--min-memory-in-gb" in argv
    assert "64" in argv


@pytest.mark.unit
def test_pod_create_omits_spot_and_min_resources_by_default(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("""
schema_version: 2
name: demo
pod:
  image: image
  datacenters: [EU-RO-1]
  gpu_order: ["gpu-a"]
storage:
  mode: ephemeral
  volume_gb: 100
run:
  script_path: /workspace/run.sh
  log_path: /workspace/run.log
  success_marker: DONE
  body: echo DONE
""")
    ctx = build_job_context(load_job_spec(config), config)

    argv = _build_pod_create_argv(ctx, volume_id=None, gpu_id="gpu-a", datacenter_id="EU-RO-1")

    assert "--spot" not in argv
    assert "--min-vcpu-count" not in argv
    assert "--min-memory-in-gb" not in argv
