from __future__ import annotations

import os
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.db import HubRepository
from app.domain import Coordinate
from app.providers.onemap import OneMapNormalizer, OneMapProvider
from app.services.optimizer import Optimizer


pytestmark = pytest.mark.integration


def _integration_enabled() -> bool:
    return os.getenv("RUN_ONEMAP_INTEGRATION", "").casefold() in {"1", "true", "yes"}


@pytest.mark.skipif(not _integration_enabled(), reason="set RUN_ONEMAP_INTEGRATION=true explicitly")
async def test_live_geocode_and_public_transport_route() -> None:
    settings = Settings.from_env()
    if not settings.onemap_email or not settings.onemap_password:
        pytest.skip("OneMap backend credentials are not configured")
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
    try:
        matches = await provider.geocode("Punggol MRT", limit=1)
        assert matches
        route = await provider.route_public_transport(
            Coordinate(1.4052, 103.9024),
            Coordinate(1.3043, 103.8322),
        )
        assert route.duration_minutes > 0
        assert route.provider == "onemap"
    finally:
        await provider.close()


@pytest.mark.skipif(not _integration_enabled(), reason="set RUN_ONEMAP_INTEGRATION=true explicitly")
async def test_live_one_and_two_errand_optimizations(tmp_path: Path) -> None:
    settings = Settings.from_env()
    if not settings.onemap_email or not settings.onemap_password:
        pytest.skip("OneMap backend credentials are not configured")
    repository = HubRepository(tmp_path / "live-optimize.db")
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
        max_candidates=3,
        max_straight_line_detour_km=20,
        dwell_times=settings.dwell_times,
        routing_soft_budget=8,
        routing_hard_budget=12,
    )
    departure = datetime.now(ZoneInfo("Asia/Singapore"))
    try:
        for errands in (["parcel"], ["groceries", "pharmacy"]):
            baseline, recommendations, diagnostics = await optimizer.optimize(
                Coordinate(1.4052, 103.9024),
                Coordinate(1.3043, 103.8322),
                list(errands),
                departure,
            )
            assert baseline.duration_minutes > 0
            assert "best_overall" in recommendations
            signatures = {
                (
                    tuple(stop.id for stop in recommendation.ordered_stops),
                    round(recommendation.incremental_detour_minutes, 3),
                    round(recommendation.incremental_walking_distance_m, 3),
                    recommendation.incremental_transfers,
                )
                for recommendation in recommendations.values()
            }
            assert len(signatures) == len(recommendations)
            assert diagnostics["routing_call_count"] <= 12
    finally:
        await provider.close()


@pytest.mark.skipif(not _integration_enabled(), reason="set RUN_ONEMAP_INTEGRATION=true explicitly")
def test_all_accepted_live_capture_fixtures_normalize() -> None:
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures" / "live"
    manifests = sorted(fixture_root.glob("*/manifest.sanitized.json"))
    if not manifests:
        pytest.skip("Run scripts/probe_onemap_pt.py to capture live fixtures first")
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    normalized_count = 0
    for entry in manifest["entries"]:
        if not entry["summary"].get("accepted"):
            continue
        fixture_path = manifests[-1].parent / entry["fixture"]
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        result = OneMapNormalizer().normalize_public_transport(fixture["response"])
        assert result.duration_minutes > 0
        normalized_count += 1
    assert normalized_count > 0
