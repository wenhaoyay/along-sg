from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import DwellTimes, ScoringWeights
from app.domain import Coordinate, Hub, RouteResult, Store
from app.providers.mock import MockOneMapProvider
from app.services.candidates import classify_stop_relationship
from app.services.optimizer import Optimizer


class RecordingProvider(MockOneMapProvider):
    def __init__(self, time_aware: bool = True):
        self.time_aware = time_aware
        self.calls: list[tuple[datetime | None, RouteResult]] = []

    @property
    def supports_departure_time_routing(self) -> bool:
        return self.time_aware

    async def route_public_transport(self, start, end, departure=None):
        result = await super().route_public_transport(start, end, departure)
        self.calls.append((departure, result))
        return result


async def test_dwell_advances_onward_departure_when_provider_support_is_verified(
    repository,
) -> None:
    provider = RecordingProvider(time_aware=True)
    optimizer = Optimizer(
        provider,
        repository,
        ScoringWeights(),
        max_candidates=1,
        max_straight_line_detour_km=20,
        dwell_times=DwellTimes(groceries=20),
        routing_soft_budget=10,
        routing_hard_budget=10,
    )
    departure = datetime(2026, 8, 27, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    _, recommendations, diagnostics = await optimizer.optimize(
        Coordinate(1.4052, 103.9024),
        Coordinate(1.3043, 103.8322),
        ["groceries"],
        departure,
    )

    candidate = recommendations["best_overall"]
    assert candidate.total_route.dwell_minutes == 20
    assert diagnostics["time_aware_dwell_applied"] is True
    candidate_first_segment = provider.calls[1]
    candidate_second_departure = provider.calls[2][0]
    assert candidate_first_segment[1].arrival_time is not None
    assert candidate.stop_arrivals == (candidate_first_segment[1].arrival_time,)
    assert candidate.stop_dwell_minutes == (20,)
    assert candidate_second_departure == (
        candidate_first_segment[1].arrival_time + timedelta(minutes=20)
    )


async def test_unverified_time_support_surfaces_limitation(repository) -> None:
    provider = RecordingProvider(time_aware=False)
    optimizer = Optimizer(
        provider,
        repository,
        ScoringWeights(),
        max_candidates=1,
        max_straight_line_detour_km=20,
        routing_soft_budget=10,
        routing_hard_budget=10,
    )
    departure = datetime(2026, 8, 27, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    _, recommendations, diagnostics = await optimizer.optimize(
        Coordinate(1.4052, 103.9024),
        Coordinate(1.3043, 103.8322),
        ["parcel"],
        departure,
    )

    assert recommendations["best_overall"].total_route.dwell_minutes == 8
    assert diagnostics["time_aware_dwell_applied"] is False
    assert recommendations["best_overall"].stop_arrivals == (None,)
    assert diagnostics["time_dependency_limitation"]
    assert all(call[0] == departure for call in provider.calls)


async def test_hard_routing_budget_is_never_exceeded(repository) -> None:
    provider = RecordingProvider(time_aware=True)
    optimizer = Optimizer(
        provider,
        repository,
        ScoringWeights(),
        max_candidates=8,
        max_straight_line_detour_km=20,
        routing_soft_budget=2,
        routing_hard_budget=3,
    )

    _, recommendations, diagnostics = await optimizer.optimize(
        Coordinate(1.4052, 103.9024),
        Coordinate(1.3043, 103.8322),
        ["groceries"],
    )

    assert recommendations
    assert diagnostics["routing_call_count"] == 3
    assert len(provider.calls) == 3
    assert diagnostics["soft_budget_exceeded"] is True
    assert diagnostics["hard_budget_reached"] is True


def test_hub_relationship_semantics_distinguish_physical_cases() -> None:
    store = (Store("Store", "groceries"),)
    mall = Hub(
        1,
        "Mall",
        Coordinate(1.30, 103.80),
        store,
        "mall",
        "station-a",
        "mall-a",
    )
    station_shop = Hub(
        2,
        "Station shop",
        Coordinate(1.301, 103.801),
        store,
        "station_area",
        "station-a",
        "station-shop",
    )
    nearby = Hub(
        3,
        "Nearby shop",
        Coordinate(1.302, 103.802),
        store,
        "standalone",
        "station-b",
        "nearby-shop",
    )
    far = Hub(
        4,
        "Far shop",
        Coordinate(1.40, 103.90),
        store,
        "standalone",
        "station-c",
        "far-shop",
    )

    assert classify_stop_relationship((mall, station_shop)) == "same_transport_hub"
    assert classify_stop_relationship((mall, nearby)) == "nearby_separate_stores"
    assert classify_stop_relationship((mall, far)) == "separate_stops"
