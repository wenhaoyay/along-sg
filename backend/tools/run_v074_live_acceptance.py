"""Run the two V0.7.4 Senja-to-Orchard live acceptance journeys."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.domain import Coordinate  # noqa: E402
from app.intent_models import IntentErrand, IntentV1  # noqa: E402
from app.main import discovery_hubs_for_intent  # noqa: E402
from app.providers.onemap import OneMapProvider  # noqa: E402
from app.providers.place_search import GeoapifyPlaceSearchProvider, TomTomPlaceSearchProvider  # noqa: E402
from app.providers.web_search import TavilyWebDiscoveryProvider  # noqa: E402
from app.services.discovery import NeedResolver  # noqa: E402
from app.services.intent_optimizer import optimize_intent  # noqa: E402
from app.services.open_needs import open_category  # noqa: E402
from app.services.optimizer import Optimizer  # noqa: E402


SINGAPORE_TZ = ZoneInfo("Asia/Singapore")
ORIGIN = Coordinate(1.3827, 103.7624)
DESTINATION = Coordinate(1.3043, 103.8322)


def recommendation_payload(candidate) -> dict:
    route = candidate.total_route
    return {
        "hubs": [hub.name for hub in candidate.ordered_stops],
        "outlets": [store.name for hub in candidate.ordered_stops for store in hub.stores],
        "total_journey_minutes": route.duration_minutes,
        "detour_minutes": candidate.incremental_detour_minutes,
        "walking_minutes": route.walking_minutes,
        "walking_distance_m": route.walking_distance_m,
        "transfers": route.transfers,
        "incremental_transfers": candidate.incremental_transfers,
        "routed_segment_count": candidate.routed_segment_count,
        "explanation": candidate.explanation,
        "classification": candidate.match_classification,
    }


async def run(output: Path) -> dict:
    settings = Settings.from_env()
    required = {
        "ONEMAP_EMAIL": settings.onemap_email,
        "ONEMAP_PASSWORD": settings.onemap_password,
        "TOMTOM_API_KEY": settings.tomtom_api_key,
        "GEOAPIFY_API_KEY": settings.geoapify_api_key,
        "TAVILY_API_KEY": settings.tavily_api_key,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("Missing required live credentials: " + ", ".join(missing))

    repository = HubRepository(settings.database_path)
    repository.initialize()
    onemap = OneMapProvider(
        settings.onemap_base_url, settings.onemap_email, settings.onemap_password,
        settings.onemap_timeout_seconds, settings.token_refresh_margin_seconds,
        max_retries=settings.onemap_max_retries,
        retry_backoff_seconds=settings.onemap_retry_backoff_seconds,
        departure_time_routing_verified=settings.onemap_departure_time_routing_verified,
    )
    tomtom = TomTomPlaceSearchProvider(
        settings.tomtom_api_key, settings.discovery_timeout_seconds,
        settings.discovery_cache_ttl_seconds, hard_budget=2,
        max_retries=settings.discovery_provider_max_retries,
    )
    geoapify = GeoapifyPlaceSearchProvider(
        settings.geoapify_api_key, settings.discovery_timeout_seconds,
        settings.discovery_cache_ttl_seconds, settings.discovery_provider_max_retries,
    )
    tavily = TavilyWebDiscoveryProvider(
        settings.tavily_api_key, settings.discovery_timeout_seconds,
    )
    resolver = NeedResolver(
        repository, tomtom, secondary_provider=geoapify, web_provider=tavily,
        primary_calls_per_need=1, secondary_calls_per_need=1,
        web_calls_per_need=1, grounding_candidate_limit=2,
    )
    optimizer = Optimizer(
        onemap, repository, settings.scoring, settings.max_candidates,
        settings.max_straight_line_detour_km, settings.dwell_times,
        settings.routing_soft_budget, settings.routing_hard_budget,
        settings.max_reasonable_detour_minutes, settings.candidate_corridor_km,
        settings.candidate_endpoint_radius_km, settings.candidate_max_transit_node_distance_m,
        settings.candidate_max_hubs_per_category, settings.route_cache_max_entries,
        settings.route_cache_ttl_seconds, settings.route_cache_departure_bucket_minutes,
        settings.routing_concurrency,
    )
    departure = datetime.now(SINGAPORE_TZ).replace(second=0, microsecond=0)
    scenarios = []
    try:
        for label, query in (("one_errand_molly_tea", "Molly Tea"), ("two_errand_mee_pok_panadol", "mee pok and Panadol")):
            context, baseline_calls, baseline_latency = await optimizer.prepare_discovery_context(
                ORIGIN, DESTINATION, departure,
            )
            parsed = resolver.parse_open_needs(query)
            discoveries = [await resolver.resolve(
                need.raw_text, limit=4, allow_live=True, context=context, open_need=need,
            ) for need in parsed]
            errands = [IntentErrand(
                category=open_category(item.original_query, index),
                discovery_concept=item.original_query,
                open_need=item.open_need,
                discovery_category=item.category,
            ) for index, item in enumerate(discoveries)]
            if not errands:
                scenarios.append({"name": label, "query": query, "status": "unresolved"})
                continue
            intent = IntentV1(original_text=query, required_errands=errands)
            hubs = await discovery_hubs_for_intent(resolver, intent, [], context)
            baseline, recommendations, diagnostics, categories = await optimize_intent(
                optimizer, ORIGIN, DESTINATION, intent, departure, hubs,
                routing_call_offset=baseline_calls,
            )
            scenarios.append({
                "name": label,
                "query": query,
                "status": "optimized" if recommendations else "no_practical_match",
                "departure": departure.isoformat(),
                "baseline": {
                    "duration_minutes": baseline.duration_minutes,
                    "walking_minutes": baseline.walking_minutes,
                    "walking_distance_m": baseline.walking_distance_m,
                    "transfers": baseline.transfers,
                },
                "discovery": [{
                    "need": item.original_query,
                    "resolved": bool(item.places),
                    "top_places": [{
                        "name": place.display_name,
                        "address": place.address,
                        "source": place.source.value,
                        "latitude": place.coordinate.latitude,
                        "longitude": place.coordinate.longitude,
                    } for place in item.places[:3]],
                    "provider_calls": item.provider_calls,
                    "latency_ms": item.latency_ms,
                    "warnings": item.warnings,
                } for item in discoveries],
                "discovered_hub_count": len(hubs),
                "optimized_categories": categories,
                "baseline_routing_calls": baseline_calls,
                "baseline_provider_latency_ms": baseline_latency,
                "optimization_diagnostics": diagnostics,
                "recommendations": {
                    key: recommendation_payload(value) for key, value in recommendations.items()
                },
            })
    finally:
        await onemap.close()
        await tomtom.close()
        await geoapify.close()
        await tavily.close()

    payload = {
        "schema_version": "v0.7.4-live-acceptance-1",
        "live_captured": True,
        "credentials_recorded": False,
        "journey": "Senja LRT Station to Orchard MRT Station",
        "scenarios": scenarios,
        "provider_totals": {
            "tomtom_calls": tomtom.calls,
            "geoapify_calls": geoapify.calls,
            "tavily_calls": tavily.calls,
            "tomtom_latency_ms": tomtom.latency_ms,
            "geoapify_latency_ms": geoapify.latency_ms,
            "tavily_latency_ms": tavily.latency_ms,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "scenario_statuses": {item["name"]: item["status"] for item in scenarios},
        "provider_totals": payload["provider_totals"],
    }, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_live:
        raise SystemExit("Refusing live calls without --run-live")
    asyncio.run(run(args.output))


if __name__ == "__main__":
    main()
