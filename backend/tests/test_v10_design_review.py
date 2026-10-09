"""What the design review needs from the API: each leg's own path, so a ride
can be drawn in its line's colour."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "design.db"))
    with TestClient(app) as test_client:
        yield test_client


def plan(client) -> dict:
    response = client.post("/api/optimize", json={
        "origin": {"query": "Punggol MRT"},
        "destination": {"query": "Orchard MRT"},
        "errands": ["groceries"],
    })
    assert response.status_code == 200
    return response.json()


def test_every_leg_carries_its_own_path(client) -> None:
    body = plan(client)
    for recommendation in body["recommendations"].values():
        for leg in recommendation["legs"]:
            assert len(leg["geometry"]) >= 2, leg["mode"]
    for leg in body["baseline"]["legs"]:
        assert len(leg["geometry"]) >= 2


def test_the_legs_together_are_the_route_line(client) -> None:
    recommendation = plan(client)["recommendations"]["best_overall"]
    joined = [point for leg in recommendation["legs"] for point in leg["geometry"]]
    whole = recommendation["route_geometry"]
    assert len(joined) == len(whole)
    for ours, theirs in zip(joined, whole):
        assert ours["latitude"] == pytest.approx(theirs["latitude"], abs=1e-6)
        assert ours["longitude"] == pytest.approx(theirs["longitude"], abs=1e-6)


def test_a_ride_path_runs_between_its_own_stations(client) -> None:
    recommendation = plan(client)["recommendations"]["best_overall"]
    rides = [leg for leg in recommendation["legs"] if leg["mode"] == "SUBWAY"]
    assert rides
    north_east = next(leg for leg in rides if leg["route_short_name"] == "NE")
    start = north_east["geometry"][0]
    # Punggol is the north-east end of the line; the leg starts there, not at
    # Orchard.
    assert start["latitude"] > 1.39 and start["longitude"] > 103.89
