"""Run bounded live one/two-errand diagnostics and write a reviewable report."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings
from app.db import HubRepository
from app.domain import Coordinate, ScoredCandidate
from app.providers.onemap import OneMapProvider
from app.services.optimizer import Optimizer


REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "live-optimization-diagnostic.md"
SINGAPORE_TZ = ZoneInfo("Asia/Singapore")


def recommendation_lines(label: str, candidate: ScoredCandidate) -> list[str]:
    outlets = [
        f"{store.name} ({store.category})"
        for hub in candidate.ordered_stops
        for store in hub.stores
        if store.category in candidate.option.required_categories
    ]
    route = candidate.total_route
    return [
        f"#### {label}",
        "",
        f"- Hubs: {' → '.join(hub.name for hub in candidate.ordered_stops)}",
        f"- Outlets: {', '.join(outlets)}",
        f"- Stop relationship: `{candidate.option.stop_relationship}`",
        f"- Total journey including dwell: {route.duration_minutes:.1f} minutes",
        f"- Detour over baseline: {candidate.incremental_detour_minutes:.1f} minutes",
        f"- Walking: {route.walking_minutes:.1f} minutes / {route.walking_distance_m:.0f} metres",
        f"- Transfers: {route.transfers} total / +{candidate.incremental_transfers} incremental",
        f"- Routed segments: {candidate.routed_segment_count}",
        f"- Expected dwell: {route.dwell_minutes:.1f} minutes",
        f"- Explanation: {candidate.explanation}",
        "",
    ]


async def main() -> int:
    settings = Settings.from_env()
    if not settings.onemap_email or not settings.onemap_password:
        print(
            "Skipped: set backend-only ONEMAP_EMAIL and ONEMAP_PASSWORD "
            "before running live optimisation diagnostics."
        )
        return 2

    repository = HubRepository(settings.database_path)
    repository.initialize()
    provider = OneMapProvider(
        settings.onemap_base_url,
        settings.onemap_email,
        settings.onemap_password,
        settings.onemap_timeout_seconds,
        settings.token_refresh_margin_seconds,
        max_retries=settings.onemap_max_retries,
        retry_backoff_seconds=settings.onemap_retry_backoff_seconds,
        departure_time_routing_verified=(
            settings.onemap_departure_time_routing_verified
        ),
    )
    optimizer = Optimizer(
        provider,
        repository,
        settings.scoring,
        max_candidates=min(settings.max_candidates, 4),
        max_straight_line_detour_km=settings.max_straight_line_detour_km,
        dwell_times=settings.dwell_times,
        routing_soft_budget=min(settings.routing_soft_budget, 10),
        routing_hard_budget=min(settings.routing_hard_budget, 15),
    )
    departure = datetime.now(SINGAPORE_TZ).replace(second=0, microsecond=0)
    scenarios = (
        ("One errand", ["parcel"]),
        ("Two errands", ["groceries", "pharmacy"]),
    )
    lines = [
        "# Live optimisation diagnostic",
        "",
        f"- Live-captured: **yes**",
        f"- Run time: {departure.isoformat()}",
        "- Journey: Punggol MRT → Orchard MRT",
        f"- Departure-time routing verified flag: `{provider.supports_departure_time_routing}`",
        "- Candidate locations: curated Singapore chain outlets in the SQLite seed",
        "",
    ]
    try:
        for scenario_name, errands in scenarios:
            baseline, recommendations, diagnostics, _ = await optimizer.optimize(
                Coordinate(1.4052, 103.9024),
                Coordinate(1.3043, 103.8322),
                errands,
                departure,
            )
            lines.extend(
                [
                    f"## {scenario_name}: {' + '.join(errands)}",
                    "",
                    f"- Baseline journey: {baseline.duration_minutes:.1f} minutes",
                    f"- Baseline walking: {baseline.walking_minutes:.1f} minutes / {baseline.walking_distance_m:.0f} metres",
                    f"- Baseline transfers: {baseline.transfers}",
                    f"- Routing calls: {diagnostics['routing_call_count']}",
                    f"- Cache hits: {diagnostics['cache_hit_count']}",
                    f"- Provider latency: {diagnostics['provider_latency_ms']} ms",
                    f"- Generated/pruned/evaluated candidates: {diagnostics['generated_candidate_count']} / {diagnostics['pruned_candidate_count']} / {diagnostics['evaluated_candidate_count']}",
                    f"- Total optimisation latency: {diagnostics['optimization_latency_ms']} ms",
                    f"- Hard budget reached: {diagnostics['hard_budget_reached']}",
                    f"- Time limitation: {diagnostics['time_dependency_limitation'] or 'none'}",
                    "",
                ]
            )
            for key, candidate in recommendations.items():
                lines.extend(
                    recommendation_lines(
                        {
                            "best_overall": "Best Overall",
                            "fastest": "Fastest",
                            "least_walking": "Least Walking",
                        }[key],
                        candidate,
                    )
                )
    finally:
        await provider.close()

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote live diagnostic report to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
