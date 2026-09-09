"""Live bus arrivals from LTA DataMall - V0.8.0, idea 1.

The payload below is LTA's own published sample response for stop 83139
(API User Guide v6.9, section 2.1), kept verbatim so this is a test of their
contract rather than of what I assumed it looked like. It happens to contain
all three cases that matter:

* service 15  - three live buses (Monitored 1)
* service 150 - two timetable buses (Monitored 0) and a padded third slot whose
                fields are all blank
* service 155 - live, and arriving sooner than 150

The guide is explicit that when buses are not running there is no response at
all, not even the attribute tags, so absence has to be an ordinary answer.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import SINGAPORE_TZ, ArrivalEstimate
from app.main import build_bus_arrival_provider, create_app
from app.providers.datamall import (
    LtaDataMallProvider,
    MockBusArrivalProvider,
    operator_name,
    parse_arrivals,
)

LTA_SAMPLE = {
    "odata.metadata": "https://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival",
    "BusStopCode": "83139",
    "Services": [
        {
            "ServiceNo": "15",
            "Operator": "GAS",
            "NextBus": {
                "OriginCode": "77009", "DestinationCode": "77009",
                "EstimatedArrival": "2024-08-14T16:41:48+08:00", "Monitored": 1,
                "Latitude": "1.3154918333333334", "Longitude": "103.9059125",
                "VisitNumber": "1", "Load": "SEA", "Feature": "WAB", "Type": "SD",
            },
            "NextBus2": {
                "OriginCode": "77009", "DestinationCode": "77009",
                "EstimatedArrival": "2024-08-14T16:49:22+08:00", "Monitored": 1,
                "Latitude": "1.3309621666666667", "Longitude": "103.9034135",
                "VisitNumber": "1", "Load": "SEA", "Feature": "WAB", "Type": "SD",
            },
            "NextBus3": {
                "OriginCode": "77009", "DestinationCode": "77009",
                "EstimatedArrival": "2024-08-14T17:06:11+08:00", "Monitored": 1,
                "Latitude": "1.344761", "Longitude": "103.94022316666667",
                "VisitNumber": "1", "Load": "SEA", "Feature": "WAB", "Type": "SD",
            },
        },
        {
            "ServiceNo": "150",
            "Operator": "SBST",
            "NextBus": {
                "OriginCode": "82009", "DestinationCode": "82009",
                "EstimatedArrival": "2024-08-14T16:55:22+08:00", "Monitored": 0,
                "Latitude": "0.0", "Longitude": "0.0",
                "VisitNumber": "1", "Load": "SEA", "Feature": "WAB", "Type": "SD",
            },
            "NextBus2": {
                "OriginCode": "82009", "DestinationCode": "82009",
                "EstimatedArrival": "2024-08-14T17:15:22+08:00", "Monitored": 0,
                "Latitude": "0.0", "Longitude": "0.0",
                "VisitNumber": "1", "Load": "SEA", "Feature": "WAB", "Type": "SD",
            },
            "NextBus3": {
                "OriginCode": "", "DestinationCode": "", "EstimatedArrival": "",
                "Monitored": 0, "Latitude": "", "Longitude": "",
                "VisitNumber": "", "Load": "", "Feature": "", "Type": "",
            },
        },
        {
            "ServiceNo": "155",
            "Operator": "SBST",
            "NextBus": {
                "OriginCode": "52009", "DestinationCode": "84009",
                "EstimatedArrival": "2024-08-14T16:45:23+08:00", "Monitored": 1,
                "Latitude": "1.3183185", "Longitude": "103.9003205",
                "VisitNumber": "1", "Load": "SEA", "Feature": "WAB", "Type": "SD",
            },
        },
    ],
}


def test_ltas_own_sample_parses_into_three_services() -> None:
    arrivals = parse_arrivals(LTA_SAMPLE)
    assert [item.service_no for item in arrivals] == ["15", "155", "150"], (
        "soonest service first - a stop can serve a dozen routes"
    )
    assert [item.operator for item in arrivals] == [
        "Go-Ahead Singapore", "SBS Transit", "SBS Transit",
    ]


def test_a_padded_slot_is_not_an_arrival() -> None:
    """NextBus3 for service 150 is a full object with every value blank.

    Counting it would put a bus on screen that does not exist.
    """
    arrivals = {item.service_no: item for item in parse_arrivals(LTA_SAMPLE)}
    assert len(arrivals["150"].estimates) == 2
    assert len(arrivals["15"].estimates) == 3
    assert len(arrivals["155"].estimates) == 1


def test_timetable_and_live_estimates_are_kept_apart() -> None:
    """Monitored is the difference between "where the bus is" and "when it is
    meant to be here". Flattening the two would be exactly the kind of
    confident wrongness this app treats as worse than saying nothing."""
    arrivals = {item.service_no: item for item in parse_arrivals(LTA_SAMPLE)}
    assert all(estimate.live for estimate in arrivals["15"].estimates)
    assert not any(estimate.live for estimate in arrivals["150"].estimates)


def test_load_feature_and_vehicle_type_survive() -> None:
    first = parse_arrivals(LTA_SAMPLE)[0].estimates[0]
    assert first.load == "SEA"
    assert first.wheelchair_accessible is True
    assert first.vehicle_type == "SD"


def test_an_absent_body_is_an_ordinary_answer() -> None:
    """LTA returns nothing at all when buses are not running, so this must not
    raise and must not read as a failure."""
    assert parse_arrivals({}) == ()
    assert parse_arrivals({"BusStopCode": "83139"}) == ()
    assert parse_arrivals({"Services": None}) == ()


def test_a_service_with_no_usable_estimate_is_dropped() -> None:
    payload = {"Services": [{"ServiceNo": "9", "NextBus": {"EstimatedArrival": ""}}]}
    assert parse_arrivals(payload) == ()


def test_an_unparsable_timestamp_is_skipped_rather_than_crashing() -> None:
    payload = {"Services": [{"ServiceNo": "9", "NextBus": {"EstimatedArrival": "soon"}}]}
    assert parse_arrivals(payload) == ()


@pytest.mark.parametrize(
    "seconds, expected",
    [(229, 3), (127, 2), (119, 1), (59, 0), (0, 0), (-90, 0)],
)
def test_minutes_round_down_and_never_go_negative(seconds: int, expected: int) -> None:
    """LTA's front-end advisement: 3:49 displays as 3, and under a minute is
    arriving rather than "0 min". A negative figure would mean counting up from
    a bus that already left."""
    now = datetime(2026, 9, 9, 12, 0, tzinfo=SINGAPORE_TZ)
    estimate = ArrivalEstimate(arrival_time=now + timedelta(seconds=seconds))
    assert estimate.minutes_away(now) == expected


def test_operator_codes_become_names_and_unknown_codes_survive() -> None:
    assert operator_name("SBST") == "SBS Transit"
    assert operator_name("GAS") == "Go-Ahead Singapore"
    assert operator_name("ZZZ") == "ZZZ"
    assert operator_name(None) is None


def test_live_mode_is_an_explicit_opt_in_not_a_side_effect_of_a_key() -> None:
    """Setting an environment variable should not silently start spending real
    quota. Mock stays until DATAMALL_MOCK is turned off."""
    assert isinstance(
        build_bus_arrival_provider(Settings(datamall_mock=True, lta_account_key="k")),
        MockBusArrivalProvider,
    )
    assert isinstance(
        build_bus_arrival_provider(Settings(datamall_mock=False, lta_account_key=None)),
        MockBusArrivalProvider,
    )
    provider = build_bus_arrival_provider(
        Settings(datamall_mock=False, lta_account_key="key")
    )
    assert isinstance(provider, LtaDataMallProvider)


def test_bus_arrival_provider_is_closed_on_app_shutdown(tmp_path, monkeypatch) -> None:
    class ClosingMockProvider(MockBusArrivalProvider):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    provider = ClosingMockProvider()
    monkeypatch.setattr("app.main.build_bus_arrival_provider", lambda _settings: provider)
    with TestClient(create_app(Settings(onemap_mock=True, database_path=tmp_path / "close.db"))):
        pass
    assert provider.closed is True


async def test_the_mock_offers_every_state_the_interface_has_to_render() -> None:
    provider = MockBusArrivalProvider()
    arrivals = await provider.arrivals("16179")
    assert {item.service_no for item in arrivals} == {"95", "196", "48"}
    assert any(estimate.live for item in arrivals for estimate in item.estimates)
    assert any(not estimate.live for item in arrivals for estimate in item.estimates)
    # Narrowing to one service must not invent the others.
    assert [item.service_no for item in await provider.arrivals("16179", "95")] == ["95"]
    # And one reserved code answers with nothing, so the empty state is reachable.
    assert await provider.arrivals(MockBusArrivalProvider.QUIET_STOP_CODE) == ()


def test_the_endpoint_refuses_anything_that_is_not_a_bus_stop_code(tmp_path) -> None:
    """A rail leg carries a station code such as NE17. Forwarding that to
    DataMall would spend a call to be told nothing."""
    with TestClient(create_app(Settings(onemap_mock=True, database_path=tmp_path / "a.db"))) as client:
        assert client.get("/api/bus-arrivals", params={"stop_code": "NE17"}).status_code == 422
        assert client.get("/api/bus-arrivals", params={"stop_code": "1234"}).status_code == 422
        assert client.get("/api/bus-arrivals", params={"stop_code": "123456"}).status_code == 422


def test_the_endpoint_says_when_its_times_are_not_real(tmp_path) -> None:
    """Sample bus times presented as live ones would be the worst kind of wrong
    this feature could be, so the source is on every response."""
    with TestClient(create_app(Settings(onemap_mock=True, database_path=tmp_path / "b.db"))) as client:
        body = client.get("/api/bus-arrivals", params={"stop_code": "16179"}).json()
        assert body["source"] == "mock"
        assert body["attribution"] is None
        assert body["services"]
        for service in body["services"]:
            for estimate in service["estimates"]:
                assert estimate["minutes"] >= 0
                assert isinstance(estimate["live"], bool)


def test_a_quiet_stop_answers_two_hundred_with_nothing_due(tmp_path) -> None:
    with TestClient(create_app(Settings(onemap_mock=True, database_path=tmp_path / "c.db"))) as client:
        response = client.get(
            "/api/bus-arrivals",
            params={"stop_code": MockBusArrivalProvider.QUIET_STOP_CODE},
        )
        assert response.status_code == 200
        assert response.json()["services"] == []


def test_the_mock_router_boards_at_a_real_looking_bus_stop_code() -> None:
    """The client decides whether to ask DataMall by testing for five digits, so
    a mock that emitted anything else would make the whole path unreachable
    offline."""
    import asyncio

    from app.domain import Coordinate
    from app.providers.mock import MockOneMapProvider

    route = asyncio.run(
        MockOneMapProvider().route_public_transport(
            Coordinate(1.3039, 103.8318),
            Coordinate(1.3005, 103.8559),
            datetime(2026, 9, 9, 9, 0, tzinfo=SINGAPORE_TZ),
        )
    )
    ride = next(leg for leg in route.legs if leg.mode in {"BUS", "SUBWAY"})
    assert ride.from_stop_code
    assert ride.departure_time is not None, "needed to tell an imminent boarding from a later one"
    if ride.mode == "BUS":
        assert ride.from_stop_code.isdigit() and len(ride.from_stop_code) == 5
    else:
        assert not ride.from_stop_code.isdigit()
