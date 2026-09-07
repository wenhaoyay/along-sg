from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import ScoringWeights, Settings
from app.db import HubRepository
from app.domain import Coordinate, RouteResult
from app.main import create_app
from app.poi_ingestion import ingest_payload, transform_osm_payload
from app.poi_taxonomy import canonical_brand, infer_categories
from app.providers.mock import MockOneMapProvider
from app.services.candidates import normalize_categories, staged_candidate_pipeline
from app.services.optimizer import Optimizer


DEPARTURE = datetime(2026, 8, 27, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
ORIGIN = Coordinate(1.4052, 103.9024)
DESTINATION = Coordinate(1.3043, 103.8322)


def test_taxonomy_normalizes_aliases_brands_and_hierarchical_categories() -> None:
    assert normalize_categories(["Fried Chicken", "ATM"]) == ("fried_chicken", "banking")
    assert canonical_brand("Kentucky Fried Chicken") == ("kfc", "KFC")
    assert infer_categories({"amenity": "fast_food", "brand": "KFC"}) == (
        "fast_food", "fried_chicken"
    )
    assert infer_categories({"amenity": "cafe", "cuisine": "bubble_tea"}) == (
        "bubble_tea", "coffee"
    )


def test_osm_ingestion_consolidates_mall_deduplicates_and_excludes_closed(tmp_path) -> None:
    payload = {
        "capture_metadata": {"captured_at": "2026-08-26T12:00:00+00:00"},
        "elements": [
            {
                "type": "way", "id": 1, "center": {"lat": 1.300, "lon": 103.800},
                "bounds": {"minlat": 1.299, "maxlat": 1.301, "minlon": 103.799, "maxlon": 103.801},
                "tags": {"shop": "mall", "name": "Test Mall"},
            },
            {"type": "node", "id": 2, "lat": 1.300, "lon": 103.800, "tags": {"railway": "station", "name": "Test MRT"}},
            {"type": "node", "id": 3, "lat": 1.3001, "lon": 103.8001, "tags": {"shop": "supermarket", "name": "FairPrice Finest", "opening_hours": "Mo-Su 08:00-22:00"}},
            {"type": "node", "id": 4, "lat": 1.30011, "lon": 103.80011, "tags": {"shop": "supermarket", "name": "FairPrice"}},
            {"type": "node", "id": 5, "lat": 1.3002, "lon": 103.8002, "tags": {"amenity": "pharmacy", "name": "Guardian", "opening_hours": "closed"}},
        ],
    }
    nodes, hubs, outlets, report = transform_osm_payload(payload)
    assert len(nodes) == 1
    assert report.deduplicated_pois == 1
    assert report.closed_pois == 1
    assert len({item["hub_source_id"] for item in outlets}) == 1

    repository = HubRepository(tmp_path / "poi.db")
    repository.initialize()
    ingest_payload(repository, payload)
    grocery_hubs = repository.find_for_categories(("groceries",))
    pharmacy_hubs = repository.find_for_categories(("pharmacy",))
    assert any(hub.name == "Test Mall" for hub in grocery_hubs)
    assert all(hub.name != "Test Mall" for hub in pharmacy_hubs)
    assert repository.stats()["known_hours"] == 2


def _bulk_records(count: int):
    hubs = []
    outlets = []
    for index in range(count):
        latitude = 1.305 + (index % 100) * 0.0008
        longitude = 103.833 + (index % 100) * 0.0005
        source_id = f"bulk:{index}"
        hubs.append({
            "name": f"Bulk hub {index}", "latitude": latitude, "longitude": longitude,
            "semantic_type": "standalone", "transport_area_id": "bulk-station",
            "consolidation_group_id": source_id, "source": "test-bulk",
            "source_id": source_id, "last_verified_at": "2026-08-26T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown",
            "transport_node_distance_m": 200.0,
        })
        outlets.append({
            "hub_source_id": source_id, "name": f"Convenience {index}",
            "brand_slug": None, "categories": ("convenience",), "source": "test-bulk",
            "source_id": f"node/{index}", "last_verified_at": "2026-08-26T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown",
        })
    return hubs, outlets


async def test_large_raw_dataset_does_not_scale_route_calls_linearly(repository) -> None:
    hubs, outlets = _bulk_records(250)
    repository.replace_source_data("test-bulk", [], hubs, outlets)
    provider = MockOneMapProvider()
    optimizer = Optimizer(
        provider, repository, ScoringWeights(), max_candidates=4,
        max_straight_line_detour_km=20, routing_soft_budget=10,
        routing_hard_budget=12,
    )
    _, recommendations, diagnostics = await optimizer.optimize(
        ORIGIN, DESTINATION, ["convenience"], DEPARTURE
    )
    assert recommendations
    assert diagnostics["raw_poi_count"] >= 280
    assert diagnostics["category_match_hub_count"] == 250
    assert diagnostics["approximate_detour_candidate_count"] == 4
    assert diagnostics["routing_call_count"] <= 9


async def test_route_cache_uses_directed_coordinate_and_one_minute_time_bucket(repository) -> None:
    optimizer = Optimizer(
        MockOneMapProvider(), repository, ScoringWeights(), 2, 20,
        routing_soft_budget=10, routing_hard_budget=12,
    )
    await optimizer.optimize(ORIGIN, DESTINATION, ["parcel"], DEPARTURE)
    _, _, repeated = await optimizer.optimize(ORIGIN, DESTINATION, ["parcel"], DEPARTURE)
    _, _, later = await optimizer.optimize(
        ORIGIN, DESTINATION, ["parcel"], DEPARTURE + timedelta(minutes=2)
    )
    assert repeated["routing_call_count"] == 0
    assert repeated["cache_hit_count"] > 0
    assert later["routing_call_count"] > 0


async def test_internal_detour_boundary_keeps_a_best_available_option(repository) -> None:
    hubs, outlets = _bulk_records(1)
    repository.replace_source_data("test-bulk", [], hubs, outlets)
    optimizer = Optimizer(
        MockOneMapProvider(), repository, ScoringWeights(), 2, 20,
        routing_soft_budget=10, routing_hard_budget=12,
        max_reasonable_detour_minutes=0,
    )
    baseline, recommendations, diagnostics = await optimizer.optimize(
        ORIGIN, DESTINATION, ["groceries"], DEPARTURE
    )
    assert isinstance(baseline, RouteResult)
    assert recommendations
    assert diagnostics["outcome"] == "best_available"
    assert recommendations["best_overall"].match_classification == "best_available"
    assert diagnostics["excessive_detour_candidate_count"] > 0
    assert diagnostics["near_miss_candidate_count"] == 1


def test_pipeline_reports_every_pruning_stage(repository) -> None:
    baseline = RouteResult(40, 8, 500, 1, provider="test")
    result = staged_candidate_pipeline(
        repository, ("groceries", "pharmacy"), ORIGIN, DESTINATION,
        baseline, max_candidates=4, max_detour_km=20,
    )
    assert result.raw_poi_count == 30
    assert result.category_match_hub_count >= result.corridor_hub_count
    assert result.corridor_hub_count >= result.transit_proximity_hub_count
    assert result.hub_coverage_candidate_count >= result.approximate_detour_candidate_count
    assert result.approximate_detour_candidate_count <= 4


class ConcurrencyRecordingProvider(MockOneMapProvider):
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0

    async def route_public_transport(self, start, end, departure=None):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return await super().route_public_transport(start, end, departure)
        finally:
            self.active -= 1


async def test_candidate_routing_concurrency_is_bounded(repository) -> None:
    provider = ConcurrencyRecordingProvider()
    optimizer = Optimizer(
        provider, repository, ScoringWeights(), 4, 20,
        routing_soft_budget=10, routing_hard_budget=12,
        routing_concurrency=2,
    )
    _, _, diagnostics = await optimizer.optimize(
        ORIGIN, DESTINATION, ["groceries"], DEPARTURE
    )
    assert provider.maximum_active == 2
    assert diagnostics["routing_concurrency"] == 2
    assert diagnostics["routing_call_count"] <= 9


def test_api_returns_best_available_beyond_internal_boundary(tmp_path) -> None:
    app = create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "no-option.db",
        max_candidates=2,
        max_straight_line_detour_km=20,
        max_reasonable_detour_minutes=0,
    ))
    with TestClient(app) as client:
        response = client.post("/api/optimize", json={
            "origin": {"query": "Punggol"},
            "destination": {"query": "Orchard"},
            "errands": ["groceries"],
        })
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "best_available"
    assert body["recommendations"]
    assert body["recommendations"]["best_overall"]["quality_label"] == "Best available"
    assert body["message"]
