from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from runpod_deploy.cli import main
from runpod_deploy.pricing import GpuPrice
from tests.conftest import FakeResult, FakeSubprocess


def _write_config(
    path: Path,
    *,
    gpu_order: tuple[str, ...] = ("NVIDIA H100 80GB HBM3", "NVIDIA A100-SXM4-80GB"),
    datacenters: tuple[str, ...] = ("US-MD-1",),
    cost_cap_usd: float = 10.0,
    assumed_rate: float = 1.65,
    cloud_type: str = "SECURE",
    spot: bool = False,
) -> Path:
    dc_yaml = "[" + ", ".join(datacenters) + "]"
    gpu_yaml = "\n    - ".join(("",) + gpu_order)
    spot_yaml = f"\n  spot: {str(spot).lower()}"
    path.write_text(f"""
schema_version: 2
name: estimate-demo
pod:
  image: img
  datacenters: {dc_yaml}
  cloud_type: {cloud_type}{spot_yaml}
  gpu_order:{gpu_yaml}
storage:
  mode: ephemeral
  volume_gb: 50
budget:
  cost_cap_usd: {cost_cap_usd}
  assumed_hourly_rate_usd: {assumed_rate}
run:
  script_path: /workspace/r.sh
  log_path: /workspace/r.log
  success_marker: DONE
  body: echo DONE
""")
    return path


def _h100() -> GpuPrice:
    return GpuPrice(
        id="NVIDIA H100 80GB HBM3",
        display_name="H100 SXM",
        secure_price=4.18,
        community_price=2.99,
        secure_spot_price=2.09,
        community_spot_price=1.49,
        lowest_price=2.99,
    )


def _a100() -> GpuPrice:
    return GpuPrice(
        id="NVIDIA A100-SXM4-80GB",
        display_name="A100 SXM",
        secure_price=2.79,
        community_price=1.89,
        secure_spot_price=1.39,
        community_spot_price=0.94,
        lowest_price=1.89,
    )


def _stub_prices(monkeypatch: pytest.MonkeyPatch, prices: dict[str, GpuPrice]) -> None:
    def fake(
        *, api_key: str | None = None, force_refresh: bool = False, **_: object
    ) -> dict[str, GpuPrice]:
        return prices

    monkeypatch.setattr("runpod_deploy.pricing.fetch_gpu_prices", fake)


def _enqueue_dc_payload(fake: FakeSubprocess, gpus: list[dict[str, str]]) -> None:
    fake.enqueue(FakeResult(stdout=json.dumps([{"id": "US-MD-1", "gpuAvailability": gpus}])))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Pricing tests should never see a real RUNPOD_API_KEY or hit the real cache."""
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_FILE", tmp_path / "cache" / "prices.json")
    yield


@pytest.mark.unit
def test_estimate_picks_first_in_order_with_graphql_price(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    _stub_prices(monkeypatch, {_h100().id: _h100(), _a100().id: _a100()})
    _enqueue_dc_payload(
        fake_subprocess,
        [
            {"gpuId": _h100().id, "stockStatus": "High"},
            {"gpuId": _a100().id, "stockStatus": "High"},
        ],
    )
    config = _write_config(tmp_path / "job.yaml", cost_cap_usd=10.0, assumed_rate=1.65)
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["estimate", str(config)])

    assert rc == 0
    out = caplog.text
    assert "selected:       NVIDIA H100 80GB HBM3 in US-MD-1" in out
    assert "$/hr:           $4.18" in out
    assert "price source:   graphql (secure)" in out
    # Spend at default timeout (cost_cap/assumed_rate * 3600 = 21818s ≈ 6.06h) at $4.18/hr ≈ $25.32
    assert "spend at budget.timeout_sec:" in out
    # Runtime at cap: 10 / 4.18 * 3600 ≈ 8612s ≈ 143min
    assert "runtime at cost_cap ceiling:" in out


@pytest.mark.unit
def test_estimate_falls_back_to_assumed_rate_when_no_prices(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    _stub_prices(monkeypatch, {})
    _enqueue_dc_payload(
        fake_subprocess, [{"gpuId": "NVIDIA H100 80GB HBM3", "stockStatus": "High"}]
    )
    config = _write_config(
        tmp_path / "job.yaml", gpu_order=("NVIDIA H100 80GB HBM3",), assumed_rate=2.50
    )
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["estimate", str(config)])

    assert rc == 0
    out = caplog.text
    assert "price source:   assumed_rate" in out
    assert "$/hr:           $2.50 (assumed)" in out


@pytest.mark.unit
def test_estimate_uses_spot_price_when_pod_spot_true(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    _stub_prices(monkeypatch, {_h100().id: _h100()})
    _enqueue_dc_payload(fake_subprocess, [{"gpuId": _h100().id, "stockStatus": "High"}])
    config = _write_config(tmp_path / "job.yaml", gpu_order=(_h100().id,), spot=True)
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["estimate", str(config)])

    assert rc == 0
    out = caplog.text
    assert "$/hr:           $2.09" in out  # secure_spot_price for H100
    assert "secure-spot" in out


@pytest.mark.unit
def test_estimate_returns_1_when_no_gpu_can_be_selected(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    _stub_prices(monkeypatch, {})
    _enqueue_dc_payload(fake_subprocess, [{"gpuId": "NVIDIA H100 80GB HBM3", "stockStatus": "Out"}])
    config = _write_config(tmp_path / "job.yaml", gpu_order=("NVIDIA H100 80GB HBM3",))
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["estimate", str(config)])

    assert rc == 1
    assert "cannot pick a GPU" in caplog.text
