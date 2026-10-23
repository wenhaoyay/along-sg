"""Recommendation quality on the real catalogue, not the twelve-mall seed.

Every other test runs on a seed where each mall has every errand, which is how
a false "why this wins", a +12 min "if convenient" coffee, a missed two-stop
plan beside the origin and a detour limit broken by shop time all passed a
green suite. These journeys run on the full OpenStreetMap capture, routed by
the offline rail network, and assert properties a person would check: the
explanation is true, the limits mean travel, and a one-errand or substitute
option is only offered when it is actually better at something.

The catalogue is built once per session into a temporary file (~15 s).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import HubRepository
from app.main import create_app
from app.ops import OpsSettings
from app.poi_ingestion import ingest_payload, load_payload

CAPTURE = Path(__file__).resolve().parents[1] / "data" / "singapore-osm-pois.json"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    if not CAPTURE.exists():
        pytest.skip("OpenStreetMap capture not present")
    database = tmp_path_factory.mktemp("golden") / "catalogue.db"
    repository = HubRepository(database)
    repository.initialize()
    ingest_payload(repository, load_payload(CAPTURE))
    settings = Settings(
        onemap_mock=True,
        database_path=database,
        analytics_database_path=database.with_suffix(".analytics.db"),
        expose_diagnostics=True,
    )
    # Many plans from one test client in seconds: the public rate limit would
    # answer 429, and it is not what these tests are about.
    with TestClient(create_app(settings, OpsSettings(rate_limit_enabled=False))) as test_client:
        yield test_client


def plan(client: TestClient, origin: str, destination: str, text: str) -> dict:
    parsed = client.post("/api/intent/parse", json={"text": text})
    assert parsed.status_code == 200, parsed.text
    preview = parsed.json()
    assert preview["status"] == "resolved", preview
    response = client.post(
        "/api/optimize-intent",
        json={
            "origin": {"query": origin},
            "destination": {"query": destination},
            "intent": preview["intent"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def offered(body: dict) -> dict[str, dict]:
    return {key: rec for key, rec in body["recommendations"].items() if rec["offered"]}


def full_matches(body: dict) -> list[dict]:
    return [
        rec
        for rec in body["recommendations"].values()
        if rec["match_classification"]
        not in {"partial_option", "substitute"}
    ]


JOURNEYS = [
    ("Punggol MRT", "Orchard MRT", "need to grab panadol and some groceries, prefer FairPrice"),
    ("Woodlands MRT", "Tanjong Pagar MRT", "buy milk"),
    ("Tampines MRT", "Orchard MRT", "groceries, and coffee if convenient"),
    ("Jurong East MRT", "Changi Airport", "KFC and bubble tea"),
    ("Bugis MRT", "City Hall MRT", "haircut and post a parcel"),
    ("Bishan MRT", "HarbourFront MRT", "bubble tea, max 5 minutes detour"),
    ("Pasir Ris MRT", "Bukit Panjang MRT", "pharmacy"),
    ("Jurong East MRT", "Raffles Place MRT", "KFC and bubble tea"),
]


@pytest.mark.parametrize(("origin", "destination", "text"), JOURNEYS)
def test_figures_and_claims_hold_together(client, origin, destination, text):
    body = plan(client, origin, destination, text)
    recommendations = offered(body)
    assert "best_overall" in recommendations
    best = recommendations["best_overall"]

    for rec in body["recommendations"].values():
        # Travel is part of the total, and the breakdown says the same thing
        # the headline does.
        assert rec["incremental_travel_minutes"] <= rec["incremental_detour_minutes"] + 0.01
        breakdown = rec["detour_breakdown"]
        assert breakdown["total_incremental_minutes"] == pytest.approx(rec["incremental_detour_minutes"], abs=0.05)
        assert breakdown["extra_transport_minutes"] == pytest.approx(rec["incremental_travel_minutes"], abs=0.1)

    # "Least extra travel" is only claimed when nothing compared beats it.
    if "least extra travel" in best["why_this_wins"]:
        quickest = min(item["incremental_travel_minutes"] for item in full_matches(body))
        assert best["incremental_travel_minutes"] <= quickest + 0.5

    # A partial or substitute next to a full match must be better at something.
    for key, rec in recommendations.items():
        if rec["match_classification"] == "partial_option":
            assert best["incremental_travel_minutes"] - rec["incremental_travel_minutes"] >= 5
        if rec["match_classification"] == "substitute":
            assert best["incremental_detour_minutes"] - rec["incremental_detour_minutes"] >= 5
        assert rec["why_this_wins"] or key.startswith("compared"), key


def test_preferred_brand_win_is_explained_by_the_brand(client):
    body = plan(client, "Punggol MRT", "Orchard MRT", "need to grab panadol and some groceries, prefer FairPrice")
    best = offered(body)["best_overall"]
    assert best["missing_preferred_brands"] == []
    quicker = [
        item
        for item in full_matches(body)
        if item["incremental_travel_minutes"] < best["incremental_travel_minutes"] - 0.5
    ]
    if quicker:
        assert "FairPrice" in best["why_this_wins"]
        assert "least extra travel" not in best["why_this_wins"]
    for item in quicker:
        assert item["match_classification"] == "without_preferred_brand"
        assert item["missing_preferred_brands"] == ["FairPrice"]


def test_optional_errand_never_costs_the_required_one(client):
    body = plan(client, "Tampines MRT", "Orchard MRT", "groceries, and coffee if convenient")
    for rec in offered(body).values():
        assert "groceries" not in rec["omitted_categories"]


def test_two_stop_plan_beside_the_origin_is_found(client):
    body = plan(client, "Jurong East MRT", "Changi Airport", "KFC and bubble tea")
    # Koi Express then JEM's KFC, both beside Jurong East, adds about 4 min of
    # travel. It used to be pruned in favour of Bugis Junction at +7.
    assert offered(body)["best_overall"]["incremental_travel_minutes"] <= 5


def test_detour_limit_is_a_limit_on_travel(client):
    body = plan(client, "Bishan MRT", "HarbourFront MRT", "bubble tea, max 5 minutes detour")
    best = offered(body)["best_overall"]
    assert best["match_classification"] != "exceeds_limit"
    assert best["incremental_travel_minutes"] <= 5
