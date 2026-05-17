"""CLI smoke tests for `runpod-deploy gpu-inventory`.

Stubs `runpodctl datacenter list` via `fake_subprocess`; asserts exit
code (0 = stocked, 3 = stock-out) and key log lines so consumer scripts
can branch on the exit code without parsing stdout.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from runpod_deploy.cli import main
from tests.conftest import FakeResult, FakeSubprocess


def _write_config(
    path: Path,
    *,
    gpu_order: tuple[str, ...] = ("H100", "A100"),
    datacenters: tuple[str, ...] = ("US-CA-1",),
) -> Path:
    dc_yaml = "[" + ", ".join(datacenters) + "]"
    gpu_yaml = "\n    - ".join(("",) + gpu_order)
    path.write_text(f"""
schema_version: 2
name: inv-demo
pod:
  image: img
  datacenters: {dc_yaml}
  cloud_type: SECURE
  gpu_order:{gpu_yaml}
storage:
  mode: ephemeral
  volume_gb: 50
budget:
  cost_cap_usd: 5.0
  assumed_hourly_rate_usd: 1.0
run:
  script_path: /workspace/r.sh
  log_path: /workspace/r.log
  success_marker: DONE
  body: echo DONE
""")
    return path


def _enqueue_datacenter_list(
    fake: FakeSubprocess,
    payload: list[dict[str, object]],
) -> None:
    """Enqueue one `runpodctl datacenter list -o json` response."""
    fake.enqueue(FakeResult(stdout=json.dumps(payload)))


@pytest.mark.unit
def test_gpu_inventory_exit_0_when_any_configured_gpu_stocked(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enqueue_datacenter_list(
        fake_subprocess,
        [
            {
                "id": "US-CA-1",
                "gpuAvailability": [
                    {"gpuId": "H100", "stockStatus": "High"},
                    {"gpuId": "A100", "stockStatus": "Unavailable"},
                ],
            }
        ],
    )
    config = _write_config(tmp_path / "job.yaml")
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-inventory", "--config", str(config)])

    assert rc == 0
    assert "ok: at least one configured GPU is currently stocked" in caplog.text
    assert "H100  available" in caplog.text
    assert "A100  stockout" in caplog.text


@pytest.mark.unit
def test_gpu_inventory_exit_3_on_full_stockout(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enqueue_datacenter_list(
        fake_subprocess,
        [
            {
                "id": "US-CA-1",
                "gpuAvailability": [
                    {"gpuId": "H100", "stockStatus": "Unavailable"},
                    {"gpuId": "A100", "stockStatus": "None"},
                ],
            }
        ],
    )
    config = _write_config(tmp_path / "job.yaml")
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-inventory", "--config", str(config)])

    assert rc == 3
    assert "stock-out" in caplog.text.lower()


@pytest.mark.unit
def test_gpu_inventory_surfaces_widening_hint_on_stockout(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enqueue_datacenter_list(
        fake_subprocess,
        [
            {
                "id": "US-CA-1",
                "gpuAvailability": [
                    {"gpuId": "H100", "stockStatus": "Unavailable"},
                    {"gpuId": "A100", "stockStatus": "Unavailable"},
                    {"gpuId": "L40S", "stockStatus": "High"},
                    {"gpuId": "A40", "stockStatus": "Medium"},
                ],
            }
        ],
    )
    config = _write_config(tmp_path / "job.yaml")
    caplog.set_level(logging.WARNING, logger="runpod_deploy")

    rc = main(["gpu-inventory", "--config", str(config)])

    assert rc == 3
    text = caplog.text
    assert "widening hint" in text
    assert "A40" in text
    assert "L40S" in text


@pytest.mark.unit
def test_gpu_inventory_walks_every_configured_datacenter(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = [
        {
            "id": "US-CA-1",
            "gpuAvailability": [{"gpuId": "H100", "stockStatus": "Unavailable"}],
        },
        {
            "id": "US-NY-1",
            "gpuAvailability": [{"gpuId": "H100", "stockStatus": "High"}],
        },
    ]
    # Each `fetch_datacenter_payload` call invokes `runpodctl datacenter list`.
    # The implementation caches at the CLI level by walking dc_list once per
    # DC; enqueue one response per call.
    _enqueue_datacenter_list(fake_subprocess, payload)
    _enqueue_datacenter_list(fake_subprocess, payload)
    config = _write_config(
        tmp_path / "job.yaml",
        gpu_order=("H100",),
        datacenters=("US-CA-1", "US-NY-1"),
    )
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-inventory", "--config", str(config)])

    assert rc == 0
    assert "datacenter: US-CA-1" in caplog.text
    assert "datacenter: US-NY-1" in caplog.text
