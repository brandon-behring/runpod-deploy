from __future__ import annotations

import json
import logging
import urllib.error
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from runpod_deploy.pricing import GpuPrice, fetch_gpu_prices, select_price_for_pod


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect the module-level cache file/dir to tmp_path for every test."""
    cache_dir = tmp_path / "cache"
    cache_file = cache_dir / "prices.json"
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_DIR", cache_dir)
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_FILE", cache_file)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    yield cache_file


class _FakeResponse:
    """Minimal context-manager response object for stubbing urlopen."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


def _stub_urlopen(
    monkeypatch: pytest.MonkeyPatch, payload: object, *, exc: Exception | None = None
) -> list[urllib.request.Request]:
    """Patch urllib.request.urlopen; capture Request objects and serve JSON."""
    seen: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> Any:
        seen.append(request)
        if exc is not None:
            raise exc
        body = json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload
        return _FakeResponse(body)

    monkeypatch.setattr("runpod_deploy.pricing.urllib.request.urlopen", fake_urlopen)
    return seen


def _ok_payload() -> dict[str, Any]:
    return {
        "data": {
            "gpuTypes": [
                {
                    "id": "NVIDIA H100 80GB HBM3",
                    "displayName": "H100 SXM",
                    "securePrice": 4.18,
                    "communityPrice": 2.99,
                    "secureSpotPrice": 2.09,
                    "communitySpotPrice": 1.49,
                    "lowestPrice": {"uninterruptablePrice": 2.99},
                },
                {
                    "id": "NVIDIA A100-SXM4-80GB",
                    "displayName": "A100 SXM",
                    "securePrice": 2.79,
                    "communityPrice": 1.89,
                    "secureSpotPrice": 1.39,
                    "communitySpotPrice": 0.94,
                    "lowestPrice": {"uninterruptablePrice": 1.89},
                },
            ]
        }
    }


@pytest.mark.unit
def test_fetch_gpu_prices_parses_graphql_response(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _stub_urlopen(monkeypatch, _ok_payload())

    prices = fetch_gpu_prices(api_key="test-key")

    assert "NVIDIA H100 80GB HBM3" in prices
    h100 = prices["NVIDIA H100 80GB HBM3"]
    assert h100 == GpuPrice(
        id="NVIDIA H100 80GB HBM3",
        display_name="H100 SXM",
        secure_price=4.18,
        community_price=2.99,
        secure_spot_price=2.09,
        community_spot_price=1.49,
        lowest_price=2.99,
    )
    assert len(requests) == 1
    assert requests[0].full_url == "https://api.runpod.io/graphql"
    assert requests[0].headers["Authorization"] == "Bearer test-key"


@pytest.mark.unit
def test_fetch_gpu_prices_reads_env_var_when_api_key_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "from-env")
    requests = _stub_urlopen(monkeypatch, _ok_payload())

    fetch_gpu_prices()

    assert requests[0].headers["Authorization"] == "Bearer from-env"


@pytest.mark.unit
def test_fetch_gpu_prices_warns_and_returns_empty_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seen = _stub_urlopen(monkeypatch, _ok_payload())
    caplog.set_level(logging.WARNING, logger="runpod_deploy.pricing")

    prices = fetch_gpu_prices()

    assert prices == {}
    assert seen == []
    assert "RUNPOD_API_KEY not set" in caplog.text


@pytest.mark.unit
def test_fetch_gpu_prices_writes_cache_then_serves_from_cache(
    monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path
) -> None:
    seen = _stub_urlopen(monkeypatch, _ok_payload())

    first = fetch_gpu_prices(api_key="k")
    second = fetch_gpu_prices(api_key="k")

    assert first == second
    assert _isolate_cache.exists()
    assert len(seen) == 1, "second call should hit the on-disk cache, not the network"


@pytest.mark.unit
def test_fetch_gpu_prices_force_refresh_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _stub_urlopen(monkeypatch, _ok_payload())

    fetch_gpu_prices(api_key="k")
    fetch_gpu_prices(api_key="k", force_refresh=True)

    assert len(seen) == 2


@pytest.mark.unit
def test_fetch_gpu_prices_cache_expires_after_ttl(
    monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path
) -> None:
    seen = _stub_urlopen(monkeypatch, _ok_payload())
    fetch_gpu_prices(api_key="k", cache_ttl_sec=3600)

    # Rewind the cache's fetched_at well past the TTL we'll request next.
    raw = json.loads(_isolate_cache.read_text())
    raw["fetched_at"] -= 10_000
    _isolate_cache.write_text(json.dumps(raw))

    fetch_gpu_prices(api_key="k", cache_ttl_sec=60)

    assert len(seen) == 2


@pytest.mark.unit
def test_fetch_gpu_prices_returns_empty_on_url_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_urlopen(monkeypatch, None, exc=urllib.error.URLError("connection refused"))
    caplog.set_level(logging.WARNING, logger="runpod_deploy.pricing")

    prices = fetch_gpu_prices(api_key="k")

    assert prices == {}
    assert "GraphQL request failed" in caplog.text


@pytest.mark.unit
def test_fetch_gpu_prices_returns_empty_on_non_json_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_urlopen(monkeypatch, b"<html>oops</html>")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.pricing")

    prices = fetch_gpu_prices(api_key="k")

    assert prices == {}
    assert "not JSON" in caplog.text


@pytest.mark.unit
def test_fetch_gpu_prices_returns_empty_on_graphql_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_urlopen(monkeypatch, {"errors": [{"message": "Unauthorized"}]})
    caplog.set_level(logging.WARNING, logger="runpod_deploy.pricing")

    prices = fetch_gpu_prices(api_key="k")

    assert prices == {}
    assert "GraphQL returned errors" in caplog.text


@pytest.mark.unit
def test_fetch_gpu_prices_skips_entries_without_id(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": {
            "gpuTypes": [
                {"displayName": "no-id"},
                {"id": "good", "displayName": "Good", "securePrice": 1.0},
            ]
        }
    }
    _stub_urlopen(monkeypatch, payload)

    prices = fetch_gpu_prices(api_key="k")

    assert "good" in prices
    assert "no-id" not in prices


@pytest.mark.unit
def test_fetch_gpu_prices_returns_empty_on_missing_data_field(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_urlopen(monkeypatch, {"data": {}})
    caplog.set_level(logging.WARNING, logger="runpod_deploy.pricing")

    prices = fetch_gpu_prices(api_key="k")

    assert prices == {}
    assert "missing 'data.gpuTypes'" in caplog.text


@pytest.mark.unit
def test_fetch_gpu_prices_handles_missing_lowest_price_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "data": {
            "gpuTypes": [
                {"id": "g1", "displayName": "G1", "securePrice": 1.0, "lowestPrice": None},
            ]
        }
    }
    _stub_urlopen(monkeypatch, payload)

    prices = fetch_gpu_prices(api_key="k")

    assert prices["g1"].lowest_price is None


@pytest.mark.unit
def test_select_price_for_pod_secure_on_demand() -> None:
    prices = {
        "g1": GpuPrice(
            id="g1",
            display_name="G1",
            secure_price=4.18,
            community_price=2.99,
            secure_spot_price=2.09,
            community_spot_price=1.49,
            lowest_price=2.99,
        )
    }
    assert select_price_for_pod(prices, gpu_id="g1", cloud_type="SECURE", spot=False) == 4.18


@pytest.mark.unit
def test_select_price_for_pod_secure_spot() -> None:
    prices = {
        "g1": GpuPrice(
            id="g1",
            display_name="G1",
            secure_price=4.18,
            community_price=2.99,
            secure_spot_price=2.09,
            community_spot_price=1.49,
            lowest_price=2.99,
        )
    }
    assert select_price_for_pod(prices, gpu_id="g1", cloud_type="SECURE", spot=True) == 2.09


@pytest.mark.unit
def test_select_price_for_pod_community_on_demand() -> None:
    prices = {
        "g1": GpuPrice(
            id="g1",
            display_name="G1",
            secure_price=4.18,
            community_price=2.99,
            secure_spot_price=2.09,
            community_spot_price=1.49,
            lowest_price=2.99,
        )
    }
    assert select_price_for_pod(prices, gpu_id="g1", cloud_type="community", spot=False) == 2.99


@pytest.mark.unit
def test_select_price_for_pod_returns_none_for_unknown_gpu_id() -> None:
    assert select_price_for_pod({}, gpu_id="missing", cloud_type="SECURE", spot=False) is None


@pytest.mark.unit
def test_select_price_for_pod_warns_on_unknown_cloud_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prices = {
        "g1": GpuPrice(
            id="g1",
            display_name="G1",
            secure_price=4.18,
            community_price=2.99,
            secure_spot_price=2.09,
            community_spot_price=1.49,
            lowest_price=2.99,
        )
    }
    caplog.set_level(logging.WARNING, logger="runpod_deploy.pricing")

    result = select_price_for_pod(prices, gpu_id="g1", cloud_type="HYBRID", spot=False)

    assert result is None
    assert "unknown pod.cloud_type" in caplog.text


@pytest.mark.unit
def test_cache_write_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    # Point the cache file at a path inside a non-writable parent.
    blocked = tmp_path / "blocked"
    blocked.write_text("file-not-dir")
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_DIR", blocked / "cache")
    monkeypatch.setattr("runpod_deploy.pricing._CACHE_FILE", blocked / "cache" / "prices.json")
    _stub_urlopen(monkeypatch, _ok_payload())
    caplog.set_level(logging.WARNING, logger="runpod_deploy.pricing")

    prices = fetch_gpu_prices(api_key="k")

    assert prices  # response still returned even when cache write fails
    assert "failed to create cache dir" in caplog.text


@pytest.mark.unit
def test_cache_with_wrong_schema_version_is_ignored(
    monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path
) -> None:
    _isolate_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_cache.write_text(json.dumps({"schema_version": 999, "fetched_at": 0, "entries": {}}))
    seen = _stub_urlopen(monkeypatch, _ok_payload())

    fetch_gpu_prices(api_key="k")

    assert len(seen) == 1, "stale-schema cache should be discarded and refetched"
