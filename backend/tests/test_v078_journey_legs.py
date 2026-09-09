"""The service identity OneMap returns, and which segment each leg belongs to.

A plan could say "37 minutes" without ever saying which train or bus to board -
the one thing the traveller has to act on. `routeShortName`, `routeLongName`,
`agencyName` and `intermediateStops` were all present in the provider response
and discarded by the parser.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain import Coordinate, RouteLeg, RouteResult
from app.providers.mock import MockOneMapProvider
from app.providers.onemap import OneMapNormalizer
from app.services.optimizer import combine_routes


DEPARTURE = datetime(2026, 9, 9, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))


def _leg(payload: dict) -> RouteLeg:
    """Parse a single leg through the real provider normaliser."""
    route = OneMapNormalizer().normalize_public_transport(
        {"plan": {"itineraries": [{
            "legs": [payload], "duration": 600, "walkTime": 0, "transfers": 0,
        }]}}
    )
    return route.legs[0]


def test_transit_legs_keep_the_service_identity() -> None:
    leg = _leg({
        "mode": "SUBWAY", "duration": 1080, "distance": 14200,
        "routeShortName": "NS", "routeLongName": "NORTH SOUTH LINE",
        "agencyName": "SMRT Corporation",
        "intermediateStops": [{}] * 17,
        "from": {"name": "WOODLANDS MRT STATION"}, "to": {"name": "MARINA BAY MRT STATION"},
    })
    assert leg.route_short_name == "NS"
    assert leg.route_long_name == "NORTH SOUTH LINE"
    assert leg.agency == "SMRT Corporation"
    # intermediateStops excludes the boarding stop.
    assert leg.stop_count == 18


def test_bus_legs_keep_their_service_number() -> None:
    leg = _leg({
        "mode": "BUS", "duration": 900, "distance": 4100,
        "routeShortName": "95", "routeLongName": "SBST BUS 95",
        "agencyName": "SBS Transit", "intermediateStops": [{}] * 9,
    })
    assert leg.route_short_name == "95"
    assert leg.stop_count == 10


def test_walking_legs_carry_no_service() -> None:
    """OneMap sends "" for a walk leg's route, which is not a name."""
    leg = _leg({"mode": "WALK", "duration": 300, "distance": 400, "route": ""})
    assert leg.route_short_name is None
    assert leg.route_long_name is None
    assert leg.agency is None
    assert leg.stop_count is None


def test_combining_segments_tags_each_leg_with_its_segment() -> None:
    """Without this the client cannot place a service against the right stop."""
    first = RouteResult(
        duration_minutes=20, walking_minutes=5, walking_distance_m=400, transfers=0,
        legs=(RouteLeg("WALK", 5, 400), RouteLeg("SUBWAY", 15, 9000, route_short_name="NE")),
    )
    second = RouteResult(
        duration_minutes=12, walking_minutes=3, walking_distance_m=250, transfers=0,
        legs=(RouteLeg("BUS", 9, 3000, route_short_name="196"), RouteLeg("WALK", 3, 250)),
    )
    combined = combine_routes([first, second], dwell_minutes=20)
    assert [leg.segment_index for leg in combined.legs] == [0, 0, 1, 1]
    # Order is travel order, so the services read in the order you board them.
    assert [leg.route_short_name for leg in combined.legs] == [None, "NE", "196", None]


async def test_mock_provider_names_a_service_so_the_timeline_works_offline() -> None:
    route = await MockOneMapProvider().route_public_transport(
        Coordinate(1.4052, 103.9024), Coordinate(1.3043, 103.8322), DEPARTURE,
    )
    rides = [leg for leg in route.legs if leg.mode not in {"WALK", "BICYCLE"}]
    assert rides, "mock route should include a ride leg"
    assert rides[0].route_short_name
    assert rides[0].stop_count and rides[0].stop_count >= 1
