"""The comparison the optimiser made is now reportable - V0.7.9, finding #9.

`optimize` routed several candidates and returned only the winners, so the map
drew one line over most of a 1440px viewport and asked to be trusted. A live
Punggol->Orchard run generated 465 candidates, routed 6 and surfaced 1. The
routed-but-rejected candidates are now returned alongside the recommendations.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import ScoringWeights, Settings
from app.domain import Coordinate
from app.main import create_app
from app.providers.mock import MockOneMapProvider
from app.services.optimizer import MAX_CONSIDERED_REPORTED, Optimizer

DEPARTURE = datetime(2026, 8, 27, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
ORIGIN = Coordinate(1.4052, 103.9024)
DESTINATION = Coordinate(1.3043, 103.8322)


def _hubs(count: int):
    """Distinct buildings spread along the origin-destination corridor."""
    hubs, outlets = [], []
    for index in range(count):
        latitude = 1.395 - index * 0.008
        longitude = 103.895 - index * 0.006
        source_id = f"compared:{index}"
        hubs.append({
            "name": f"Compared hub {index}", "latitude": latitude, "longitude": longitude,
            "semantic_type": "mall", "transport_area_id": f"area-{index}",
            "consolidation_group_id": source_id, "source": "test-compared",
            "source_id": source_id, "last_verified_at": "2026-08-26T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown",
            "transport_node_distance_m": 60.0,
        })
        outlets.append({
            "hub_source_id": source_id, "name": f"Shop {index}",
            "brand_slug": None, "categories": ("groceries",), "source": "test-compared",
            "source_id": f"node/{index}", "last_verified_at": "2026-08-26T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown",
        })
    return hubs, outlets


def _optimizer(repository, **kwargs):
    return Optimizer(
        MockOneMapProvider(), repository, ScoringWeights(),
        max_candidates=kwargs.pop("max_candidates", 6),
        max_straight_line_detour_km=20,
        routing_soft_budget=40, routing_hard_budget=60, routing_concurrency=4,
        **kwargs,
    )


async def test_routed_losers_are_returned_instead_of_discarded(repository) -> None:
    hubs, outlets = _hubs(6)
    repository.replace_source_data("test-compared", [], hubs, outlets)
    _, recommendations, diagnostics, considered = await _optimizer(repository).optimize(
        ORIGIN, DESTINATION, ["groceries"], DEPARTURE
    )
    assert recommendations
    # The whole point: more was routed than was recommended, and the surplus is
    # no longer thrown away.
    assert diagnostics["evaluated_candidate_count"] > len(recommendations)
    assert considered, "candidates were routed and compared but not reported"
    assert len(considered) == diagnostics["evaluated_candidate_count"] - len(recommendations)


async def test_a_reported_candidate_is_never_also_a_recommendation(repository) -> None:
    """Otherwise the map would draw the plan twice, once dimmed."""
    hubs, outlets = _hubs(6)
    repository.replace_source_data("test-compared", [], hubs, outlets)
    _, recommendations, _, considered = await _optimizer(repository).optimize(
        ORIGIN, DESTINATION, ["groceries"], DEPARTURE
    )
    recommended = {
        frozenset(stop.id for stop in item.ordered_stops) for item in recommendations.values()
    }
    for candidate in considered:
        assert frozenset(stop.id for stop in candidate.ordered_stops) not in recommended


async def test_the_same_building_is_reported_once(repository) -> None:
    """A multi-stop option is evaluated once per permutation of its stops, and
    those permutations are the same places in a different order."""
    hubs, outlets = _hubs(6)
    for index, hub in enumerate(hubs):
        outlets.append({
            "hub_source_id": hub["source_id"], "name": f"Pharmacy {index}",
            "brand_slug": None, "categories": ("pharmacy",), "source": "test-compared",
            "source_id": f"node/p{index}",
            "last_verified_at": "2026-08-26T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown",
        })
    repository.replace_source_data("test-compared", [], hubs, outlets)
    _, _, _, considered = await _optimizer(repository).optimize(
        ORIGIN, DESTINATION, ["groceries", "pharmacy"], DEPARTURE
    )
    stop_sets = [frozenset(stop.id for stop in item.ordered_stops) for item in considered]
    assert len(stop_sets) == len(set(stop_sets))


async def test_the_reported_set_is_capped(repository) -> None:
    """Beyond a handful the markers stop being readable and start being noise."""
    hubs, outlets = _hubs(24)
    repository.replace_source_data("test-compared", [], hubs, outlets)
    _, _, _, considered = await _optimizer(repository, max_candidates=24).optimize(
        ORIGIN, DESTINATION, ["groceries"], DEPARTURE
    )
    assert len(considered) == MAX_CONSIDERED_REPORTED


async def test_the_best_of_the_losers_is_reported_first(repository) -> None:
    hubs, outlets = _hubs(8)
    repository.replace_source_data("test-compared", [], hubs, outlets)
    _, _, _, considered = await _optimizer(repository, max_candidates=8).optimize(
        ORIGIN, DESTINATION, ["groceries"], DEPARTURE
    )
    scores = [item.overall_score for item in considered]
    assert scores == sorted(scores)


def test_the_api_returns_compared_options_as_selectable_recommendations(tmp_path) -> None:
    """A compared option is a recommendation the app did not volunteer.

    You can pick one off the map, and the moment you do it needs its own legs,
    geometry and per-shop detail - so it is rendered as what it is, flagged
    rather than reshaped. It also reports extra travel through the same
    breakdown as the headline, which is the figure V0.7.7 moved to.
    """
    settings = Settings(onemap_mock=True, database_path=tmp_path / "api.db")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/optimize", json={
            "origin": {"coordinate": {
                "latitude": ORIGIN.latitude, "longitude": ORIGIN.longitude,
            }},
            "destination": {"coordinate": {
                "latitude": DESTINATION.latitude, "longitude": DESTINATION.longitude,
            }},
            "errands": ["groceries"],
        })
        assert response.status_code == 200
        body = response.json()
        offered = {key: item for key, item in body["recommendations"].items() if item["offered"]}
        compared = {
            key: item for key, item in body["recommendations"].items() if not item["offered"]
        }
        assert offered, "nothing was recommended"
        assert compared, "the seed catalogue routes more than it recommends"
        for key, option in compared.items():
            assert key.startswith("compared_")
            # Selectable means complete: without these a click cannot draw a plan.
            assert option["stops"], key
            assert option["legs"], key
            assert option["detour_breakdown"]["extra_transport_minutes"] >= 0
            # Strictly less than total added time, not merely not-greater:
            # groceries carry dwell, so equality would mean the two figures had
            # been wired to the same value.
            assert (
                option["detour_breakdown"]["extra_transport_minutes"]
                < option["incremental_detour_minutes"]
            )
