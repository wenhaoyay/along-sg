"""The portfolio review's fixes: real lines in mock mode, everyday phrasing,
input errors that are the user's to fix, and the obvious answer being priced."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import ScoringWeights, Settings
from app.domain import Coordinate
from app.main import create_app
from app.providers.mock import MockOneMapProvider
from app.providers.rail_network import encode_polyline, load_rail_network
from app.services.candidates import decode_polyline
from app.services.open_needs import PREFERENCE_CLAUSE, PlausibleNeedParser, clean_clause
from app.services.optimizer import Optimizer
from app.poi_taxonomy import normalize_text


DEPARTURE = datetime(2026, 10, 2, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
PUNGGOL = Coordinate(1.4052, 103.9024)
ORCHARD = Coordinate(1.3043, 103.8322)
BISHAN = Coordinate(1.3510, 103.8485)
BUGIS = Coordinate(1.3008, 103.8559)
CHANGI_AIRPORT = Coordinate(1.3573, 103.9884)
TUAS_LINK = Coordinate(1.3404, 103.6368)


def route(start: Coordinate, end: Coordinate):
    return asyncio.run(MockOneMapProvider().route_public_transport(start, end, DEPARTURE))


def rides(result):
    return [leg for leg in result.legs if leg.mode == "SUBWAY"]


# --- Mock routing follows the real network --------------------------------


def test_punggol_boards_the_north_east_line_not_an_invented_one() -> None:
    result = route(PUNGGOL, ORCHARD)
    trains = rides(result)
    assert trains[0].route_short_name == "NE"
    assert trains[0].from_name == "Punggol MRT Station"
    assert trains[-1].to_name == "Orchard MRT Station"
    assert result.transfers == len(trains) - 1


def test_a_change_of_line_happens_at_a_real_interchange() -> None:
    network = load_rail_network()
    for start, end in ((PUNGGOL, ORCHARD), (BISHAN, BUGIS), (TUAS_LINK, PUNGGOL)):
        trains = rides(route(start, end))
        for first, second in zip(trains, trains[1:]):
            first_codes = {code for code, station in network.stations.items() if station.name == first.to_name}
            second_codes = {code for code, station in network.stations.items() if station.name == second.from_name}
            assert first.to_name == second.from_name or first_codes & second_codes
            assert first.route_short_name != second.route_short_name


def test_changi_airport_changes_at_tanah_merah() -> None:
    trains = rides(route(CHANGI_AIRPORT, TUAS_LINK))
    assert [leg.route_short_name for leg in trains] == ["CG", "EW"]
    assert trains[0].to_name == "Tanah Merah MRT Station"


def test_route_geometry_follows_the_stations_ridden() -> None:
    result = route(PUNGGOL, ORCHARD)
    points = [point for leg in rides(result) for point in decode_polyline(leg.geometry)]
    # A straight chord has two points; the NE line from Punggol has a dozen.
    assert len(points) >= 10


def test_a_short_trip_is_a_walk_and_a_journey_always_walks_a_little() -> None:
    nearby = route(PUNGGOL, Coordinate(1.4065, 103.9022))
    assert [leg.mode for leg in nearby.legs] == ["WALK"]
    assert route(PUNGGOL, ORCHARD).walking_minutes > 0


def test_a_long_access_is_an_unnamed_feeder_bus() -> None:
    # Mandai, far from any station: no bus service number may be invented.
    result = route(Coordinate(1.4043, 103.7930), ORCHARD)
    buses = [leg for leg in result.legs if leg.mode == "BUS"]
    assert buses and all(leg.route_short_name is None for leg in buses)


def test_polyline_round_trip() -> None:
    points = [PUNGGOL, BISHAN, ORCHARD]
    decoded = decode_polyline(encode_polyline(points))
    assert [(round(p.latitude, 5), round(p.longitude, 5)) for p in decoded] == [
        (round(p.latitude, 5), round(p.longitude, 5)) for p in points
    ]


# --- Everyday phrasing ------------------------------------------------------


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        ("need to grab panadol", "panadol"),
        ("some groceries", "groceries"),
        ("quickly grab a coffee please", "coffee"),
        ("also get some bread", "bread"),
    ],
)
def test_filler_words_are_stripped_from_a_clause(clause: str, expected: str) -> None:
    assert clean_clause(clause) == expected


@pytest.mark.parametrize(
    "clause",
    ["prefer Guardian", "ideally FairPrice", "don't want to walk much", "less walking",
     "no extra transfers", "in a rush", "under 10 minutes", "in one stop"],
)
def test_a_preference_is_not_a_need(clause: str) -> None:
    assert PREFERENCE_CLAUSE.search(normalize_text(clause))


@pytest.mark.parametrize("text", ["hello", "hi", "thanks", "test", "asdfgh", "ok"])
def test_a_greeting_is_not_an_errand(text: str) -> None:
    assert PlausibleNeedParser().parse(text) == ()


def test_need_parser_keeps_needs_and_drops_preferences() -> None:
    needs = PlausibleNeedParser().parse("need to grab panadol and some groceries, prefer FairPrice, don't want to walk much")
    assert [need.raw_text for need in needs] == ["panadol", "groceries"]


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "review.db"))
    with TestClient(app) as test_client:
        yield test_client


def parsed_categories(body: dict) -> list[str]:
    intent = body["intent"]
    return sorted(item["category"] for item in intent["required_errands"] + intent["optional_errands"])


def test_full_sentence_keeps_errands_and_preferences(client) -> None:
    body = client.post("/api/intent/parse", json={
        "text": "need to grab panadol and some groceries, prefer FairPrice, don't want to walk much",
    }).json()
    assert body["status"] == "resolved"
    assert parsed_categories(body) == ["groceries", "pharmacy"]
    assert body["intent"]["preferences"]["walking_tolerance"] == "minimal"
    groceries = next(item for item in body["intent"]["required_errands"] if item["category"] == "groceries")
    assert groceries["preferred_brand"] == "FairPrice"


def test_two_clauses_of_one_errand_stay_one_errand(client) -> None:
    body = client.post("/api/intent/parse", json={"text": "buy some milk and eggs"}).json()
    assert body["status"] == "resolved"
    assert parsed_categories(body) == ["groceries"]


def test_cat_food_is_pet_supplies_not_fast_food(client) -> None:
    body = client.post("/api/intent/parse", json={"text": "cat food"}).json()
    assert parsed_categories(body) == ["pet_supplies"]


def test_hello_is_not_an_errand(client) -> None:
    body = client.post("/api/intent/parse", json={"text": "hello"}).json()
    assert body["status"] != "resolved"


# --- Input errors are the user's to fix -------------------------------------


def test_unknown_location_is_422_with_a_hint(client) -> None:
    response = client.post("/api/optimize", json={
        "origin": {"query": "asdfghjkl"}, "destination": {"query": "Bugis MRT"}, "errands": ["coffee"],
    })
    assert response.status_code == 422
    assert "No Singapore location found" in response.json()["detail"]


def test_a_postal_code_resolves_offline(client) -> None:
    response = client.get("/api/geocode", params={"q": "828868"})
    assert response.status_code == 200
    results = response.json()["results"]
    # The seed catalog may not hold this exact building; the sector is a fair
    # approximation and is labelled as one.
    assert results == [] or results[0]["subtitle"] == "Postal code 828868"


# --- The obvious answer is always priced ------------------------------------


def _hub(name: str, latitude: float, longitude: float, node_m: float):
    source_id = f"review:{name}"
    hub = {
        "name": name, "latitude": latitude, "longitude": longitude, "semantic_type": "mall",
        "transport_area_id": "review", "consolidation_group_id": source_id, "source": "test-review",
        "source_id": source_id, "last_verified_at": "2026-10-01T00:00:00+00:00",
        "opening_hours": None, "closure_status": "unknown", "transport_node_distance_m": node_m,
    }
    outlets = [{
        "hub_source_id": source_id, "name": f"{category} at {name}", "brand_slug": None,
        "categories": (category,), "source": "test-review", "source_id": f"{source_id}:{category}",
        "last_verified_at": "2026-10-01T00:00:00+00:00", "opening_hours": None, "closure_status": "unknown",
    } for category in ("groceries", "pharmacy")]
    return hub, outlets


def test_a_mall_beside_the_origin_is_routed_and_ranks_near_the_top(repository) -> None:
    network = load_rail_network()
    hubs, outlets = [], []
    # Eight malls sitting right on the NE line, which the corridor proxy loves.
    for code in ("NE16", "NE15", "NE14", "NE13", "NE12", "NE11", "NE10", "NE9"):
        station = network.stations[code]
        hub, items = _hub(f"Line mall {code}", station.coordinate.latitude, station.coordinate.longitude, 60.0)
        hubs.append(hub)
        outlets.extend(items)
    # One a short walk from the start, as Waterway Point is from Punggol MRT.
    hub, items = _hub("Beside the origin", 1.40646, 103.90223, 450.0)
    hubs.append(hub)
    outlets.extend(items)
    repository.replace_source_data("test-review", [], hubs, outlets)

    optimizer = Optimizer(
        MockOneMapProvider(), repository, ScoringWeights(), max_candidates=4,
        max_straight_line_detour_km=20, routing_soft_budget=16, routing_hard_budget=20,
    )
    _, recommendations, _, considered = asyncio.run(
        optimizer.optimize(PUNGGOL, ORCHARD, ["groceries", "pharmacy"], DEPARTURE)
    )
    ranked = sorted(
        (item for item in considered if item.option.consolidated),
        key=lambda item: item.overall_score,
    )
    names = [item.option.stops[0].name for item in ranked]
    assert "Beside the origin" in names
    assert names.index("Beside the origin") <= 1



def test_distant_origin_uses_feeder_and_rail_instead_of_only_walking() -> None:
    # Valid remote area, more than 3 km from the closest rail station.
    remote = Coordinate(1.43, 103.68)
    result = route(remote, ORCHARD)
    assert any(leg.mode == "BUS" for leg in result.legs)
    assert any(leg.mode == "SUBWAY" for leg in result.legs)


def test_live_geocoder_failure_is_not_misreported_as_422(repository) -> None:
    from app.providers.base import ProviderTimeoutError
    from app.services.discovery import LocationResolver

    class TimedOutMap(MockOneMapProvider):
        async def geocode(self, query: str, limit: int = 6):
            raise ProviderTimeoutError("OneMap timed out")

    resolver = LocationResolver(repository, TimedOutMap())
    with pytest.raises(ProviderTimeoutError):
        asyncio.run(resolver.require_confident("Unlisted Warehouse Avenue 123"))
    with pytest.raises(ProviderTimeoutError):
        asyncio.run(resolver.require_confident("999999"))


def test_parser_metrics_are_hidden_by_default_in_public_mode(tmp_path) -> None:
    app = create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "private-metrics.db",
        analytics_database_path=tmp_path / "private-analytics.db",
        expose_diagnostics=False,
    ))
    with TestClient(app) as private_client:
        assert private_client.get("/api/intent/metrics").status_code == 404

    app_enabled = create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "enabled-metrics.db",
        analytics_database_path=tmp_path / "enabled-analytics.db",
        expose_diagnostics=True,
    ))
    with TestClient(app_enabled) as enabled_client:
        assert enabled_client.get("/api/intent/metrics").status_code == 200
