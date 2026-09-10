from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.domain import Coordinate  # noqa: E402
from app.main import build_provider  # noqa: E402
from app.presentation import hub_display_name, hub_location_context  # noqa: E402
from app.services.optimizer import Optimizer  # noqa: E402


CASES = (
    ("Punggol-Orchard fried chicken", Coordinate(1.4052, 103.9024), Coordinate(1.3043, 103.8322), ["fried_chicken"]),
    ("Jurong East-Bugis coffee", Coordinate(1.3331, 103.7422), Coordinate(1.3008, 103.8559), ["coffee"]),
    ("Tampines-Orchard bubble tea", Coordinate(1.3533, 103.9451), Coordinate(1.3043, 103.8322), ["bubble_tea"]),
    ("Punggol-Orchard groceries and pharmacy", Coordinate(1.4052, 103.9024), Coordinate(1.3043, 103.8322), ["groceries", "pharmacy"]),
    ("Jurong East-Tampines convenience and ATM", Coordinate(1.3331, 103.7422), Coordinate(1.3533, 103.9451), ["convenience", "banking"]),
    ("Bugis-VivoCity electronics and coffee", Coordinate(1.3008, 103.8559), Coordinate(1.2643, 103.8223), ["electronics", "coffee"]),
)


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percent
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def optimizer_for(settings: Settings, provider, repository: HubRepository) -> Optimizer:
    return Optimizer(
        provider, repository, settings.scoring, settings.max_candidates,
        settings.max_straight_line_detour_km, settings.dwell_times,
        settings.routing_soft_budget, settings.routing_hard_budget,
        settings.max_reasonable_detour_minutes, settings.candidate_corridor_km,
        settings.candidate_endpoint_radius_km,
        settings.candidate_max_transit_node_distance_m,
        settings.candidate_max_hubs_per_category, settings.route_cache_max_entries,
        settings.route_cache_ttl_seconds,
        settings.route_cache_departure_bucket_minutes,
        settings.routing_concurrency,
    )


async def run(live: bool, output: Path) -> dict:
    settings = replace(Settings.from_env(), onemap_mock=not live)
    if live and not (settings.onemap_email and settings.onemap_password):
        raise RuntimeError("Live benchmark requires backend-only OneMap credentials")
    repository = HubRepository(settings.database_path)
    repository.initialize()
    provider = build_provider(settings)
    optimizer = optimizer_for(settings, provider, repository)
    departure = datetime.now(ZoneInfo("Asia/Singapore")).replace(
        hour=10, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    results = []
    try:
        for name, origin, destination, errands in CASES:
            baseline, recommendations, diagnostics, _ = await optimizer.optimize(
                origin, destination, errands, departure
            )
            winner = recommendations.get("best_overall")
            results.append({
                "case": name,
                "errands": errands,
                "baseline_minutes": baseline.duration_minutes,
                "outcome": diagnostics["outcome"],
                "winner": [hub_display_name(hub) for hub in winner.ordered_stops] if winner else [],
                "winner_location_context": [
                    hub_location_context(hub).context
                    for hub in winner.ordered_stops
                ] if winner else [],
                "detour_minutes": winner.incremental_detour_minutes if winner else None,
                "walking_minutes": winner.total_route.walking_minutes if winner else None,
                "transfers": winner.total_route.transfers if winner else None,
                "raw_poi_count": diagnostics["raw_poi_count"],
                "category_match_hubs": diagnostics["category_match_hub_count"],
                "corridor_hubs": diagnostics["corridor_hub_count"],
                "transit_proximity_hubs": diagnostics["transit_proximity_hub_count"],
                "hub_coverage_candidates": diagnostics["hub_coverage_candidate_count"],
                "approximate_detour_candidates": diagnostics["approximate_detour_candidate_count"],
                "routing_budget_candidates": diagnostics["routing_budget_candidate_count"],
                "evaluated_candidates": diagnostics["evaluated_candidate_count"],
                "route_calls": diagnostics["routing_call_count"],
                "cache_hits": diagnostics["cache_hit_count"],
                "provider_latency_ms": diagnostics["provider_latency_ms"],
                "total_latency_ms": diagnostics["optimization_latency_ms"],
                "hard_budget_reached": diagnostics["hard_budget_reached"],
            })
    finally:
        close = getattr(provider, "close", None)
        if close is not None:
            await close()

    latencies = [float(item["total_latency_ms"]) for item in results]
    calls = [int(item["route_calls"]) for item in results]
    cache_hits = sum(int(item["cache_hits"]) for item in results)
    call_total = sum(calls)
    report = {
        "stage": "V0.7.2",
        "mode": "live-onemap" if live else "deterministic-mock",
        "captured_at": datetime.now(ZoneInfo("Asia/Singapore")).isoformat(),
        "departure": departure.isoformat(),
        "poi_database": repository.stats(),
        "summary": {
            "case_count": len(results),
            "average_route_calls": round(mean(calls), 2),
            "worst_route_calls": max(calls),
            "cache_hit_rate": round(cache_hits / (cache_hits + call_total), 4) if cache_hits + call_total else 0,
            "p50_latency_ms": round(percentile(latencies, 0.50), 2),
            "p95_latency_ms": round(percentile(latencies, 0.95), 2),
            "average_provider_latency_ms": round(mean(float(item["provider_latency_ms"]) for item in results), 2),
            "recommendations_lacking_location_context": sum(
                context.casefold() == "location details unavailable"
                for item in results
                for context in item["winner_location_context"]
            ),
        },
        "cases": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark V0.5 candidate pruning and routing budgets")
    parser.add_argument("--live", action="store_true", help="Explicitly use live OneMap")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    default_name = "v05-benchmark-live.json" if args.live else "v05-benchmark-mock.json"
    report = await run(args.live, args.output or ROOT / "docs" / default_name)
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
