"""Request validation: times in Singapore time, bounded inputs, and the
overall optimisation timeout."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import SINGAPORE_TZ
from app.main import create_app
from app.schemas import IntentOptimizeRequest, OptimizeRequest

PUNGGOL = {"coordinate": {"latitude": 1.4052, "longitude": 103.9024}}
ORCHARD = {"coordinate": {"latitude": 1.3043, "longitude": 103.8322}}


def client_for(tmp_path: Path, **settings) -> TestClient:
    return TestClient(create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "poi.db",
        analytics_database_path=tmp_path / "analytics.db",
        **settings,
    )))


def optimize_body(**values) -> dict:
    return {"origin": PUNGGOL, "destination": ORCHARD, "errands": ["groceries"], **values}


def intent_body(**values) -> dict:
    return {
        "origin": PUNGGOL,
        "destination": ORCHARD,
        "intent": {
            "original_text": "groceries",
            "required_errands": [{"category": "groceries", "required": True}],
        },
        **values,
    }


def naive_in_an_hour() -> str:
    return (datetime.now(SINGAPORE_TZ) + timedelta(hours=1)).replace(tzinfo=None).isoformat()


# Request times ------------------------------------------------------------

def test_naive_departure_is_singapore_time() -> None:
    naive = datetime.now(SINGAPORE_TZ).replace(tzinfo=None) + timedelta(hours=1)
    request = OptimizeRequest.model_validate(optimize_body(departure=naive.isoformat()))
    assert request.departure.tzinfo is not None
    assert request.departure.replace(tzinfo=None) == naive
    assert request.departure.utcoffset() == timedelta(hours=8)


def test_aware_departure_is_converted_to_singapore_time() -> None:
    utc = datetime.now(UTC) + timedelta(hours=1)
    request = OptimizeRequest.model_validate(optimize_body(departure=utc.isoformat()))
    assert request.departure == utc
    assert request.departure.utcoffset() == timedelta(hours=8)


def test_naive_arrival_by_is_singapore_time() -> None:
    body = intent_body()
    body["intent"]["preferences"] = {"arrival_by": "2099-01-01T10:00:00"}
    request = IntentOptimizeRequest.model_validate(body)
    assert request.intent.preferences.arrival_by == datetime(2099, 1, 1, 10, tzinfo=SINGAPORE_TZ)


@pytest.mark.parametrize("path, body", [
    ("/api/optimize", optimize_body),
    ("/api/optimize-intent", intent_body),
])
def test_naive_departure_plans_instead_of_failing(tmp_path: Path, path: str, body) -> None:
    with client_for(tmp_path) as client:
        response = client.post(path, json=body(departure=naive_in_an_hour()))
        assert response.status_code == 200, response.text
        # And again, now that the route cache holds the first answer.
        assert client.post(path, json=body(departure=naive_in_an_hour())).status_code == 200


def test_naive_arrival_by_plans_instead_of_failing(tmp_path: Path) -> None:
    body = intent_body(departure=naive_in_an_hour())
    arrive = (datetime.now(SINGAPORE_TZ) + timedelta(hours=4)).replace(tzinfo=None)
    body["intent"]["preferences"] = {"arrival_by": arrive.isoformat()}
    with client_for(tmp_path) as client:
        response = client.post("/api/optimize-intent", json=body)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("path, body", [
    ("/api/optimize", optimize_body),
    ("/api/optimize-intent", intent_body),
])
def test_departure_in_the_past_is_refused(tmp_path: Path, path: str, body) -> None:
    stale = (datetime.now(SINGAPORE_TZ) - timedelta(minutes=10)).isoformat()
    recent = (datetime.now(SINGAPORE_TZ) - timedelta(minutes=2)).isoformat()
    with client_for(tmp_path) as client:
        refused = client.post(path, json=body(departure=stale))
        assert refused.status_code == 422
        assert "past" in str(refused.json()["detail"])
        # A form submitted a minute or two late is still a plan.
        assert client.post(path, json=body(departure=recent)).status_code == 200


# Input bounds -------------------------------------------------------------

def test_errand_strings_and_counts_are_bounded(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        assert client.post("/api/optimize", json=optimize_body(errands=["x" * 121])).status_code == 422
        assert client.post(
            "/api/optimize", json=optimize_body(errands=["groceries", "pharmacy", "coffee"])
        ).status_code == 422
        assert client.post("/api/optimize", json=optimize_body(errands=[""])).status_code == 422
        long_query = {"query": "x" * 121}
        assert client.post(
            "/api/optimize", json=optimize_body(origin=long_query)
        ).status_code == 422
        assert client.post("/api/intent/parse", json={"text": "x" * 301}).status_code == 422
        assert client.get("/api/geocode", params={"q": "x" * 121}).status_code == 422


# Timeout ------------------------------------------------------------------

def test_optimize_has_an_overall_timeout(tmp_path: Path) -> None:
    with client_for(tmp_path, optimization_timeout_seconds=0.05) as client:
        async def slow_optimize(*args, **kwargs):
            await asyncio.sleep(5)

        client.app.state.optimizer.optimize = slow_optimize
        response = client.post("/api/optimize", json=optimize_body())
    assert response.status_code == 504
    assert response.json() == {
        "detail": "Optimization timed out before a bounded result was available."
    }
