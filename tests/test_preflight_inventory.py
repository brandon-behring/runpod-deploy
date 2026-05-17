"""Unit tests for `preflight.report_gpu_inventory` + `InventoryReport`.

Covers the structured-report sibling of `check_gpu_availability`: same
probe (`fetch_datacenter_payload`), but returns data instead of raising
so the CLI can render a stock report and exit non-zero on stock-out
without RuntimeError-as-control-flow.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from runpod_deploy.config import JobContext, build_job_context, load_job_spec
from runpod_deploy.preflight import (
    DatacenterInventory,
    InventoryReport,
    report_gpu_inventory,
)


def _write_config(
    path: Path,
    *,
    gpu_order: tuple[str, ...] = ("H100", "A100"),
    datacenters: tuple[str, ...] = ("US-CA-1", "US-NY-1"),
) -> Path:
    dc_yaml = "[" + ", ".join(datacenters) + "]"
    gpu_yaml = "\n    - ".join(("",) + gpu_order)
    path.write_text(f"""
schema_version: 2
name: inventory-demo
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


def _build_ctx(tmp_path: Path, **kwargs: Any) -> JobContext:
    config_path = _write_config(tmp_path / "job.yaml", **kwargs)
    return build_job_context(load_job_spec(config_path), config_path)


def _stub_datacenter_payloads(
    monkeypatch: pytest.MonkeyPatch,
    per_dc: dict[str, list[dict[str, str]]],
) -> None:
    """Patch `preflight.fetch_datacenter_payload` to return canned per-DC data."""

    def fake(dc_id: str) -> Mapping[str, Any]:
        return {"id": dc_id, "gpuAvailability": per_dc[dc_id]}

    monkeypatch.setattr("runpod_deploy.preflight.fetch_datacenter_payload", fake)


@pytest.mark.unit
def test_report_full_intersection_all_dcs_stocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_datacenter_payloads(
        monkeypatch,
        {
            "US-CA-1": [
                {"gpuId": "H100", "stockStatus": "High"},
                {"gpuId": "A100", "stockStatus": "Medium"},
            ],
            "US-NY-1": [
                {"gpuId": "H100", "stockStatus": "Medium"},
                {"gpuId": "A100", "stockStatus": "High"},
            ],
        },
    )
    ctx = _build_ctx(tmp_path)

    report = report_gpu_inventory(ctx)

    assert isinstance(report, InventoryReport)
    assert report.any_stocked is True
    assert report.gpu_order == ("H100", "A100")
    assert len(report.datacenters) == 2
    ca = report.datacenters[0]
    assert ca.datacenter_id == "US-CA-1"
    assert ca.configured_available == ("H100", "A100")
    assert ca.configured_low_stock == ()
    assert ca.configured_stockout == ()
    assert ca.configured_unknown == ()


@pytest.mark.unit
def test_report_empty_intersection_marks_stockout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_datacenter_payloads(
        monkeypatch,
        {
            "US-CA-1": [
                {"gpuId": "H100", "stockStatus": "Unavailable"},
                {"gpuId": "A100", "stockStatus": "None"},
            ],
            "US-NY-1": [
                {"gpuId": "H100", "stockStatus": ""},
                {"gpuId": "A100", "stockStatus": "Out"},
            ],
        },
    )
    ctx = _build_ctx(tmp_path)

    report = report_gpu_inventory(ctx)

    assert report.any_stocked is False
    for dc in report.datacenters:
        assert dc.configured_available == ()
        assert dc.configured_low_stock == ()
        assert dc.configured_stockout == ("H100", "A100")


@pytest.mark.unit
def test_report_partial_intersection_one_dc_stocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_datacenter_payloads(
        monkeypatch,
        {
            "US-CA-1": [
                {"gpuId": "H100", "stockStatus": "Unavailable"},
                {"gpuId": "A100", "stockStatus": "Unavailable"},
            ],
            "US-NY-1": [
                {"gpuId": "H100", "stockStatus": "High"},
                {"gpuId": "A100", "stockStatus": "Unavailable"},
            ],
        },
    )
    ctx = _build_ctx(tmp_path)

    report = report_gpu_inventory(ctx)

    assert report.any_stocked is True
    ca, ny = report.datacenters
    assert ca.configured_available == ()
    assert ca.configured_stockout == ("H100", "A100")
    assert ny.configured_available == ("H100",)
    assert ny.configured_stockout == ("A100",)


@pytest.mark.unit
def test_report_low_stock_counts_as_stocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_datacenter_payloads(
        monkeypatch,
        {
            "US-CA-1": [{"gpuId": "H100", "stockStatus": "Low"}],
            "US-NY-1": [{"gpuId": "H100", "stockStatus": "Unavailable"}],
        },
    )
    ctx = _build_ctx(tmp_path, gpu_order=("H100",))

    report = report_gpu_inventory(ctx)

    assert report.any_stocked is True
    ca = report.datacenters[0]
    assert ca.configured_available == ()
    assert ca.configured_low_stock == ("H100",)


@pytest.mark.unit
def test_report_unknown_gpu_separated_from_stockout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_datacenter_payloads(
        monkeypatch,
        {
            "US-CA-1": [{"gpuId": "H100", "stockStatus": "High"}],
            "US-NY-1": [{"gpuId": "H100", "stockStatus": "High"}],
        },
    )
    ctx = _build_ctx(tmp_path, gpu_order=("H100", "MYTHICAL_GPU"))

    report = report_gpu_inventory(ctx)

    for dc in report.datacenters:
        assert dc.configured_available == ("H100",)
        assert dc.configured_unknown == ("MYTHICAL_GPU",)
        assert dc.configured_stockout == ()


@pytest.mark.unit
def test_report_other_available_lists_widening_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_datacenter_payloads(
        monkeypatch,
        {
            "US-CA-1": [
                {"gpuId": "H100", "stockStatus": "Unavailable"},
                {"gpuId": "A100", "stockStatus": "Unavailable"},
                {"gpuId": "L40S", "stockStatus": "High"},
                {"gpuId": "A40", "stockStatus": "Medium"},
            ],
            "US-NY-1": [
                {"gpuId": "H100", "stockStatus": "Unavailable"},
                {"gpuId": "A100", "stockStatus": "Unavailable"},
                {"gpuId": "A40", "stockStatus": "High"},
            ],
        },
    )
    ctx = _build_ctx(tmp_path)

    report = report_gpu_inventory(ctx)

    assert report.any_stocked is False
    ca, ny = report.datacenters
    assert ca.other_available == ("A40", "L40S")
    assert ny.other_available == ("A40",)


@pytest.mark.unit
def test_report_other_available_excludes_unavailable_gpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GPU outside gpu_order that is itself stock-out should NOT be in the widening hint."""
    _stub_datacenter_payloads(
        monkeypatch,
        {
            "US-CA-1": [
                {"gpuId": "H100", "stockStatus": "High"},
                {"gpuId": "L40S", "stockStatus": "Unavailable"},
                {"gpuId": "A40", "stockStatus": "Low"},
            ],
            "US-NY-1": [{"gpuId": "H100", "stockStatus": "High"}],
        },
    )
    ctx = _build_ctx(tmp_path, gpu_order=("H100",))

    report = report_gpu_inventory(ctx)

    assert report.datacenters[0].other_available == ("A40",)


@pytest.mark.unit
def test_dataclasses_are_frozen() -> None:
    """CLAUDE.md §5 invariant: value/report dataclasses are frozen + slotted."""
    inv = DatacenterInventory(
        datacenter_id="X",
        configured_available=(),
        configured_low_stock=(),
        configured_stockout=(),
        configured_unknown=(),
        other_available=(),
    )
    report = InventoryReport(gpu_order=(), datacenters=())
    with pytest.raises(AttributeError):
        inv.datacenter_id = "Y"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        report.gpu_order = ("Z",)  # type: ignore[misc]
