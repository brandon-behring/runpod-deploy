from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from runpod_deploy.cli import main
from runpod_deploy.pricing import GpuPrice


def _stub_prices(monkeypatch: pytest.MonkeyPatch, prices: dict[str, GpuPrice]) -> list[bool]:
    """Patch pricing.fetch_gpu_prices to return canned data; capture force_refresh values."""
    seen: list[bool] = []

    def fake_fetch(
        *, api_key: str | None = None, force_refresh: bool = False, **_: object
    ) -> dict[str, GpuPrice]:
        seen.append(force_refresh)
        return prices

    monkeypatch.setattr("runpod_deploy.pricing.fetch_gpu_prices", fake_fetch)
    return seen


def _stub_datacenter(monkeypatch: pytest.MonkeyPatch, gpus: list[dict[str, str]]) -> None:
    """Patch preflight.fetch_datacenter_payload to return one DC entry with the given GPUs."""

    def fake_fetch_dc(_dc_id: str) -> dict[str, object]:
        return {"id": _dc_id, "gpuAvailability": gpus}

    monkeypatch.setattr("runpod_deploy.preflight.fetch_datacenter_payload", fake_fetch_dc)


@pytest.fixture
def _isolate_pricing_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cache_dir = tmp_path / "cache"
    cache_file = cache_dir / "prices.json"
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_DIR", cache_dir)
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_FILE", cache_file)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    yield cache_file


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


@pytest.mark.unit
def test_gpu_prices_prints_sorted_table_secure_on_demand(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_prices(monkeypatch, {"H100": _h100(), "A100": _a100()})
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-prices"])

    assert rc == 0
    # A100 ($2.79) should appear before H100 ($4.18) in the sorted output.
    out = caplog.text
    assert out.index("A100") < out.index("H100")
    assert "$2.79" in out
    assert "$4.18" in out


@pytest.mark.unit
def test_gpu_prices_spot_flag_uses_spot_field(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_prices(monkeypatch, {"H100": _h100()})
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-prices", "--spot"])

    assert rc == 0
    assert "$2.09" in caplog.text  # secure_spot_price for H100
    assert "secure-spot" in caplog.text


@pytest.mark.unit
def test_gpu_prices_community_cloud(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_prices(monkeypatch, {"H100": _h100()})
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-prices", "--cloud-type", "COMMUNITY"])

    assert rc == 0
    assert "$2.99" in caplog.text  # community_price for H100


@pytest.mark.unit
def test_gpu_prices_no_price_cache_passes_force_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _stub_prices(monkeypatch, {"H100": _h100()})

    main(["gpu-prices", "--no-price-cache"])

    assert seen == [True]


@pytest.mark.unit
def test_gpu_prices_returns_1_and_warns_when_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_prices(monkeypatch, {})
    caplog.set_level(logging.WARNING, logger="runpod_deploy")

    rc = main(["gpu-prices"])

    assert rc == 1
    assert "no prices returned" in caplog.text


@pytest.mark.unit
def test_gpu_list_adds_price_column_when_prices_available(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_datacenter(
        monkeypatch,
        [
            {"gpuId": "NVIDIA H100 80GB HBM3", "stockStatus": "High"},
            {"gpuId": "NVIDIA A100-SXM4-80GB", "stockStatus": "Low"},
        ],
    )
    _stub_prices(monkeypatch, {"NVIDIA H100 80GB HBM3": _h100(), "NVIDIA A100-SXM4-80GB": _a100()})
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    rc = main(["gpu-list", "--datacenter", "EU-RO-1"])

    assert rc == 0
    out = caplog.text
    assert "$/hr (secure)" in out
    assert "$4.18" in out  # H100 secure price
    assert "$2.79" in out  # A100 secure price


@pytest.mark.unit
def test_gpu_list_no_prices_flag_skips_pricing_fetch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_datacenter(monkeypatch, [{"gpuId": "H100", "stockStatus": "High"}])
    seen = _stub_prices(monkeypatch, {"H100": _h100()})
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    main(["gpu-list", "--datacenter", "EU-RO-1", "--no-prices"])

    assert seen == [], "--no-prices should skip the pricing call entirely"
    assert "$/hr" not in caplog.text


@pytest.mark.unit
def test_gpu_list_falls_back_to_no_price_column_when_fetch_returns_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_datacenter(monkeypatch, [{"gpuId": "H100", "stockStatus": "High"}])
    _stub_prices(monkeypatch, {})  # no prices available
    caplog.set_level(logging.INFO, logger="runpod_deploy")

    main(["gpu-list", "--datacenter", "EU-RO-1"])

    out = caplog.text
    assert "$/hr" not in out  # no price column when nothing to show
    assert "H100" in out
