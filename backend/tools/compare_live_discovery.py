from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.discovery_models import DiscoverySearchContext  # noqa: E402
from app.domain import Coordinate  # noqa: E402
from app.providers.place_search import (  # noqa: E402
    GeoapifyPlaceSearchProvider,
    LivePlaceSearchError,
    TomTomPlaceSearchProvider,
)


QUERIES = (
    "Molly Tea", "mee pok", "Panadol", "printer ink", "cat food",
    "passport photo", "Bangkit LRT", "313 Somerset", "mala", "USB-C cable",
)
SINGAPORE_CONTEXT = DiscoverySearchContext(center=Coordinate(1.3521, 103.8198), radius_m=20_000)


async def run_provider(provider, queries: tuple[str, ...]) -> dict:
    results: list[dict] = []
    for query in queries:
        started = time.perf_counter()
        try:
            places = await provider.search(query, limit=5, context=SINGAPORE_CONTEXT)
            results.append({
                "query": query,
                "status": "ok",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "hits": [{
                    "name": place.display_name,
                    "address": place.address,
                    "latitude": place.coordinate.latitude,
                    "longitude": place.coordinate.longitude,
                    "category": place.category,
                } for place in places],
            })
        except LivePlaceSearchError as error:
            results.append({
                "query": query, "status": "provider_error",
                "error": str(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2), "hits": [],
            })
    summary = {"provider": provider.name, "calls": provider.calls, "latency_ms": provider.latency_ms, "results": results}
    await provider.close()
    return summary


async def compare(queries: tuple[str, ...]) -> dict:
    settings = Settings.from_env()
    providers = []
    if settings.tomtom_api_key:
        providers.append(TomTomPlaceSearchProvider(
            settings.tomtom_api_key,
            timeout_seconds=settings.discovery_timeout_seconds,
            cache_ttl_seconds=settings.discovery_cache_ttl_seconds,
            max_retries=settings.discovery_provider_max_retries,
        ))
    if settings.geoapify_api_key:
        providers.append(GeoapifyPlaceSearchProvider(
            settings.geoapify_api_key, settings.discovery_timeout_seconds,
            settings.discovery_cache_ttl_seconds, settings.discovery_provider_max_retries,
        ))
    if not providers:
        return {
            "status": "not_run",
            "reason": "TOMTOM_API_KEY and GEOAPIFY_API_KEY are both absent.",
            "providers": [],
        }
    return {
        "status": "completed",
        "providers": [await run_provider(provider, queries) for provider in providers],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded, secret-free Singapore live place-provider comparison")
    parser.add_argument("--limit", type=int, default=len(QUERIES), choices=range(1, len(QUERIES) + 1))
    parser.add_argument("--output", type=Path, help="Optional JSON output path; never contains provider keys")
    parser.add_argument("queries", nargs="*", help="Optional explicit bounded query list")
    args = parser.parse_args()
    queries = tuple(args.queries) if args.queries else QUERIES[:args.limit]
    if len(queries) > 20:
        parser.error("at most 20 explicit queries are allowed")
    result = asyncio.run(compare(queries))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
