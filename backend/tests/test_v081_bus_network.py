"""The static bus network - V0.8.1, the second half of idea 1.

Live arrivals answer "when is the next 95". This answers what has to be asked
first, "is the 95 running here at all", which is the only way to tell "nothing
due" apart from "stopped for the night". LTA's own advisement names those as
separate states and says the second needs the Bus Routes dataset.

Field names are LTA's, from API User Guide v6.9 sections 2.3 and 2.4 -
`WD_FirstBus`, `SAT_LastBus`, `SUN_FirstBus`. They are not the names some
third-party bindings use, and the samples below are the guide's.

Not yet verified against the live API: fetching anything at all needs an
AccountKey, so these test the transform and the storage against the documented
shapes rather than against a real capture.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.bus_network import (
    is_in_operation,
    operating_hours_text,
    stop_display_name,
    transform_bus_routes,
    transform_bus_stops,
    window_for,
)
from app.config import Settings
from app.domain import SINGAPORE_TZ
from app.main import create_app

GUIDE_STOP = {
    "BusStopCode": "01012",
    "RoadName": "Victoria St",
    "Description": "Hotel Grand Pacific",
    "Latitude": 1.29685,
    "Longitude": 103.853,
}

GUIDE_ROUTE = {
    "ServiceNo": "107M",
    "Operator": "SBST",
    "Direction": 1,
    "StopSequence": 28,
    "BusStopCode": "01012",
    "Distance": 10.3,
    "WD_FirstBus": "2025",
    "WD_LastBus": "2352",
    "SAT_FirstBus": "1427",
    "SAT_LastBus": "2349",
    "SUN_FirstBus": "0620",
    "SUN_LastBus": "2349",
}

# Runs past midnight, and does not run on Sundays at all.
NIGHT_ROUTE = {
    **GUIDE_ROUTE,
    "ServiceNo": "2",
    "StopSequence": 1,
    "WD_FirstBus": "0530",
    "WD_LastBus": "0015",
    "SAT_FirstBus": "0530",
    "SAT_LastBus": "0015",
    "SUN_FirstBus": "-",
    "SUN_LastBus": "",
}

WEDNESDAY_2300 = datetime(2026, 9, 9, 23, 0, tzinfo=SINGAPORE_TZ)
SUNDAY_1000 = datetime(2026, 9, 13, 10, 0, tzinfo=SINGAPORE_TZ)


def test_the_guides_sample_stop_and_route_transform() -> None:
    stop = transform_bus_stops([GUIDE_STOP])[0]
    assert stop["stop_code"] == "01012"
    assert stop["description"] == "Hotel Grand Pacific"
    assert stop_display_name(stop) == "Hotel Grand Pacific, Victoria St"
    route = transform_bus_routes([GUIDE_ROUTE])[0]
    assert route["service_no"] == "107M"
    assert route["distance_km"] == pytest.approx(10.3)
    assert route["weekday_first"] == "2025"
    assert route["sunday_last"] == "2349"


@pytest.mark.parametrize(
    "code",
    ["0101", "010123", "abcde", "", "0101a"],
)
def test_anything_that_is_not_a_five_digit_code_is_dropped(code: str) -> None:
    """The code is the join key to a live arrival. A malformed one would be
    stored and then never match anything."""
    assert transform_bus_stops([{**GUIDE_STOP, "BusStopCode": code}]) == []
    assert transform_bus_routes([{**GUIDE_ROUTE, "BusStopCode": code}]) == []


def test_a_stop_at_the_null_island_is_dropped() -> None:
    """0,0 is a placeholder, and keeping it would put a Singapore bus stop in
    the Atlantic - and drag the map's framing there with it."""
    assert transform_bus_stops([{**GUIDE_STOP, "Latitude": 0.0, "Longitude": 0.0}]) == []
    assert transform_bus_stops([{**GUIDE_STOP, "Latitude": "not a number"}]) == []


def test_a_repeated_row_does_not_become_two() -> None:
    """Pages can overlap when a capture is retried, and a route is identified by
    service, direction and sequence rather than by arriving twice."""
    assert len(transform_bus_stops([GUIDE_STOP, GUIDE_STOP])) == 1
    assert len(transform_bus_routes([GUIDE_ROUTE, GUIDE_ROUTE])) == 1


def test_the_right_day_of_the_week_is_used() -> None:
    route = transform_bus_routes([GUIDE_ROUTE])[0]
    assert window_for(route, WEDNESDAY_2300) == ("2025", "2352")
    assert window_for(route, datetime(2026, 9, 12, 15, 0, tzinfo=SINGAPORE_TZ)) == (
        "1427", "2349",
    )
    assert window_for(route, SUNDAY_1000) == ("0620", "2349")


def test_a_window_that_crosses_midnight_still_contains_the_night() -> None:
    """A last bus after midnight is published as a smaller number than the
    first: 0015 against 0530. Compared naively the service looks closed for
    twenty-three of every twenty-four hours."""
    route = transform_bus_routes([NIGHT_ROUTE])[0]
    assert is_in_operation(route, WEDNESDAY_2300) is True
    assert is_in_operation(route, datetime(2026, 9, 9, 0, 10, tzinfo=SINGAPORE_TZ)) is True
    assert is_in_operation(route, datetime(2026, 9, 9, 3, 0, tzinfo=SINGAPORE_TZ)) is False
    assert is_in_operation(route, datetime(2026, 9, 9, 6, 0, tzinfo=SINGAPORE_TZ)) is True


def test_an_unpublished_window_is_unknown_rather_than_closed() -> None:
    """None and False are different answers. Reporting "not running" because a
    timetable is missing invents the very fact this dataset was added to
    establish."""
    route = transform_bus_routes([NIGHT_ROUTE])[0]
    assert route["sunday_first"] is None
    assert is_in_operation(route, SUNDAY_1000) is None
    assert operating_hours_text(route, SUNDAY_1000) is None


def test_midnight_is_a_real_last_bus() -> None:
    route = transform_bus_routes([{**GUIDE_ROUTE, "WD_LastBus": "2400"}])[0]
    assert route["weekday_last"] == "2400"
    assert "midnight" in (operating_hours_text(route, WEDNESDAY_2300) or "")


def test_operating_hours_read_as_a_sentence() -> None:
    route = transform_bus_routes([GUIDE_ROUTE])[0]
    assert operating_hours_text(route, WEDNESDAY_2300) == "First bus 20:25, last bus 23:52"


def test_the_network_is_replaced_whole_and_never_emptied(repository) -> None:
    """LTA publishes a complete snapshot, so a retired stop has to disappear -
    but a truncated fetch must not be allowed to empty the tables and leave
    every service looking cancelled."""
    stops = transform_bus_stops([GUIDE_STOP])
    routes = transform_bus_routes([GUIDE_ROUTE, NIGHT_ROUTE])
    assert repository.replace_bus_network(stops, routes, "2026-09-09") == (1, 2)
    assert repository.bus_network_counts() == (1, 2)
    # Idempotent: the same capture twice is the same network.
    repository.replace_bus_network(stops, routes, "2026-09-09")
    assert repository.bus_network_counts() == (1, 2)
    with pytest.raises(ValueError):
        repository.replace_bus_network([], routes)
    with pytest.raises(ValueError):
        repository.replace_bus_network(stops, [])
    assert repository.bus_network_counts() == (1, 2), "a refused write changed nothing"


def test_services_at_a_stop_come_back_with_their_windows(repository) -> None:
    repository.replace_bus_network(
        transform_bus_stops([GUIDE_STOP]),
        transform_bus_routes([GUIDE_ROUTE, NIGHT_ROUTE]),
    )
    rows = repository.bus_routes_at_stop("01012")
    assert [row["service_no"] for row in rows] == ["107M", "2"]
    assert repository.bus_routes_at_stop("99999") == []
    assert repository.bus_stop("01012")["road_name"] == "Victoria St"
    assert repository.bus_stop("99999") is None


def test_the_endpoint_cannot_say_whether_a_service_runs_without_the_network(tmp_path) -> None:
    """A fresh clone has no bus network, and the honest answer there is silence
    rather than a guess in either direction."""
    settings = Settings(onemap_mock=True, database_path=tmp_path / "n.db")
    with TestClient(create_app(settings)) as client:
        body = client.get(
            "/api/bus-arrivals", params={"stop_code": "01012", "service": "107M"}
        ).json()
        assert body["in_operation"] is None
        assert body["operating_hours"] is None
        assert body["stop_name"] is None


def test_the_endpoint_reports_operating_hours_once_the_network_is_there(tmp_path) -> None:
    from app.db import HubRepository

    database = tmp_path / "m.db"
    repository = HubRepository(database)
    repository.initialize()
    repository.replace_bus_network(
        transform_bus_stops([GUIDE_STOP]),
        transform_bus_routes([GUIDE_ROUTE, NIGHT_ROUTE]),
    )
    with TestClient(create_app(Settings(onemap_mock=True, database_path=database))) as client:
        body = client.get(
            "/api/bus-arrivals", params={"stop_code": "01012", "service": "107M"}
        ).json()
        assert body["stop_name"] == "Hotel Grand Pacific, Victoria St"
        assert body["in_operation"] in {True, False}
        assert body["operating_hours"].startswith("First bus")
        # A service that does not call here at all is still unknown rather than
        # reported as stopped.
        other = client.get(
            "/api/bus-arrivals", params={"stop_code": "01012", "service": "999"}
        ).json()
        assert other["in_operation"] is None


async def test_paging_stops_when_a_server_ignores_skip() -> None:
    """`$skip` is not documented in v6.9, so it is not promised either.

    A server that ignored it would hand back page one forever, and a fetcher
    that trusted the page size would loop until MAX_PAGES with 100,000
    duplicate rows to show for it. The fetcher stops when a page repeats.
    """
    import httpx

    from scripts.ingest_bus_network import fetch_all

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        # Always the same page, whatever is asked for.
        return httpx.Response(200, json={"value": [{"BusStopCode": "01012"}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        records = await fetch_all(client, "/BusStops", "key")
    assert calls == 2, "one page, then one repeat that ends it"
    assert len(records) == 1


async def test_paging_walks_until_a_page_comes_back_empty() -> None:
    import httpx

    from scripts.ingest_bus_network import fetch_all

    pages = {
        0: [{"BusStopCode": f"{i:05d}"} for i in range(500)],
        500: [{"BusStopCode": f"{i:05d}"} for i in range(500, 700)],
        1000: [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params.get("$skip", 0))
        assert request.headers["AccountKey"] == "key"
        return httpx.Response(200, json={"value": pages.get(skip, [])})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await fetch_all(client, "/BusStops", "key")
    assert len(records) == 700
