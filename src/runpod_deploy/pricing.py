"""GraphQL pricing client for RunPod GPUs.

POSTs to ``https://api.runpod.io/graphql`` (auth: ``Authorization: Bearer
$RUNPOD_API_KEY``) for the ``gpuTypes`` query. Caches results on disk at
``~/.cache/runpod-deploy/prices.json`` with a 1-hour TTL so the typical
"explore prices → edit YAML → run" flow makes one network request per
hour. Errors map to WARNING + empty/None returns — pricing must never
abort a deploy.

Stdlib-only (``urllib.request``, ``json``); no new pip deps.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "VOLUME_STORAGE_USD_PER_GB_MONTH",
    "GpuPrice",
    "estimate_volume_storage_cost_usd_per_day",
    "fetch_gpu_prices",
    "select_price_for_pod",
]

VOLUME_STORAGE_USD_PER_GB_MONTH: Final[float] = 0.10
"""RunPod's standard preserved-volume rate per GB per month (2026)."""


def estimate_volume_storage_cost_usd_per_day(volume_in_gb: int) -> float:
    """Estimate daily volume-disk storage cost for a stopped/preserved pod.

    Uses :data:`VOLUME_STORAGE_USD_PER_GB_MONTH` and divides by 30 days.
    Returns 0.0 for ``volume_in_gb <= 0``.
    """
    if volume_in_gb <= 0:
        return 0.0
    return volume_in_gb * VOLUME_STORAGE_USD_PER_GB_MONTH / 30.0


logger = logging.getLogger(__name__)

GRAPHQL_ENDPOINT = "https://api.runpod.io/graphql"
DEFAULT_CACHE_TTL_SEC = 3600
_REQUEST_TIMEOUT_SEC = 30
_CACHE_SCHEMA_VERSION = 1
_CACHE_DIR = Path.home() / ".cache" / "runpod-deploy"
_CACHE_FILE = _CACHE_DIR / "prices.json"

_GPU_TYPES_QUERY = """
query GpuTypes {
  gpuTypes {
    id
    displayName
    securePrice
    communityPrice
    secureSpotPrice
    communitySpotPrice
    lowestPrice {
      uninterruptablePrice
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class GpuPrice:
    """Per-GPU pricing snapshot from RunPod's GraphQL gpuTypes query."""

    id: str
    display_name: str
    secure_price: float | None
    community_price: float | None
    secure_spot_price: float | None
    community_spot_price: float | None
    lowest_price: float | None


def fetch_gpu_prices(
    *,
    api_key: str | None = None,
    force_refresh: bool = False,
    cache_ttl_sec: int = DEFAULT_CACHE_TTL_SEC,
) -> dict[str, GpuPrice]:
    """Fetch per-GPU pricing from RunPod GraphQL.

    Reads ``RUNPOD_API_KEY`` env var when ``api_key`` is None. Uses the
    on-disk cache at ``~/.cache/runpod-deploy/prices.json`` (1h TTL by
    default); pass ``force_refresh=True`` to bypass.

    Returns an empty dict + WARNING when the API key is missing, the
    HTTP request fails, or the response is malformed. Never raises.
    """
    if not force_refresh:
        cached = _read_cache(cache_ttl_sec)
        if cached is not None:
            return cached
    key = api_key if api_key is not None else os.environ.get("RUNPOD_API_KEY", "")
    if not key:
        logger.warning("[pricing] RUNPOD_API_KEY not set; cannot fetch GraphQL prices")
        return {}
    raw = _post_graphql(key)
    if raw is None:
        return {}
    prices = _parse_payload(raw)
    if prices:
        _write_cache(prices)
    return prices


def select_price_for_pod(
    prices: dict[str, GpuPrice],
    *,
    gpu_id: str,
    cloud_type: str,
    spot: bool,
) -> float | None:
    """Pick the price field for a given ``pod.cloud_type`` and ``pod.spot``."""
    price = prices.get(gpu_id)
    if price is None:
        return None
    cloud = cloud_type.upper()
    if cloud == "SECURE":
        return price.secure_spot_price if spot else price.secure_price
    if cloud == "COMMUNITY":
        return price.community_spot_price if spot else price.community_price
    logger.warning(f"[pricing] unknown pod.cloud_type {cloud_type!r}; expected SECURE or COMMUNITY")
    return None


def _post_graphql(api_key: str) -> dict[str, Any] | None:
    body = json.dumps({"query": _GPU_TYPES_QUERY}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SEC) as resp:
            data = resp.read()
    except urllib.error.URLError as exc:
        logger.warning(f"[pricing] GraphQL request failed: {exc}")
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        logger.warning(f"[pricing] GraphQL response is not JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        logger.warning(f"[pricing] GraphQL response is {type(payload).__name__}, expected object")
        return None
    if payload.get("errors"):
        logger.warning(f"[pricing] GraphQL returned errors: {payload['errors']}")
        return None
    return payload


def _parse_payload(payload: dict[str, Any]) -> dict[str, GpuPrice]:
    data = payload.get("data")
    types = data.get("gpuTypes") if isinstance(data, dict) else None
    if not isinstance(types, list):
        logger.warning(
            "[pricing] GraphQL response missing 'data.gpuTypes' list; "
            f"got {type(types).__name__}"
        )
        return {}
    out: dict[str, GpuPrice] = {}
    for entry in types:
        if not isinstance(entry, dict):
            continue
        gpu_id = str(entry.get("id") or "")
        if not gpu_id:
            continue
        lowest_block = entry.get("lowestPrice")
        lowest_uninterruptable: float | None = None
        if isinstance(lowest_block, dict):
            lowest_uninterruptable = _as_optional_float(lowest_block.get("uninterruptablePrice"))
        out[gpu_id] = GpuPrice(
            id=gpu_id,
            display_name=str(entry.get("displayName") or ""),
            secure_price=_as_optional_float(entry.get("securePrice")),
            community_price=_as_optional_float(entry.get("communityPrice")),
            secure_spot_price=_as_optional_float(entry.get("secureSpotPrice")),
            community_spot_price=_as_optional_float(entry.get("communitySpotPrice")),
            lowest_price=lowest_uninterruptable,
        )
    return out


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_cache(ttl_sec: int) -> dict[str, GpuPrice] | None:
    if not _CACHE_FILE.exists():
        return None
    try:
        raw = json.loads(_CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[pricing] cache read failed: {exc}")
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None
    fetched_at = raw.get("fetched_at")
    if not isinstance(fetched_at, (int, float)) or time.time() - fetched_at > ttl_sec:
        return None
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return None
    try:
        return {
            gpu_id: GpuPrice(**fields)
            for gpu_id, fields in entries.items()
            if isinstance(fields, dict)
        }
    except TypeError as exc:
        logger.warning(f"[pricing] cache entry shape mismatch (regenerating): {exc}")
        return None


def _write_cache(prices: dict[str, GpuPrice]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(f"[pricing] failed to create cache dir {_CACHE_DIR}: {exc}")
        return
    payload: dict[str, Any] = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "fetched_at": time.time(),
        "entries": {
            gpu_id: {
                "id": price.id,
                "display_name": price.display_name,
                "secure_price": price.secure_price,
                "community_price": price.community_price,
                "secure_spot_price": price.secure_spot_price,
                "community_spot_price": price.community_spot_price,
                "lowest_price": price.lowest_price,
            }
            for gpu_id, price in prices.items()
        },
    }
    try:
        _CACHE_FILE.write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        logger.warning(f"[pricing] failed to write cache {_CACHE_FILE}: {exc}")
