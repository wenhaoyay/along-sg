from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import HubRepository
from app.main import create_app
from app.poi_ingestion import ingest_payload
from app.presentation import safe_label
from app.providers.mock import MockOneMapProvider


async def test_location_autocomplete_handles_misspelling_and_rejects_nonsense() -> None:
    provider = MockOneMapProvider()
    matches = await provider.geocode("chuachukang")
    assert matches[0].label == "Choa Chu Kang MRT Station"
    assert await provider.geocode("totally invented abcxyz") == []


def test_journey_conflicts_and_non_errands_are_structured(tmp_path: Path) -> None:
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "quality.db"))
    endpoints = {
        "origin": {"label": "Boon Lay MRT Station", "coordinate": {"latitude": 1.3386, "longitude": 103.7061}},
        "destination": {"label": "Fajar LRT Station", "coordinate": {"latitude": 1.3845, "longitude": 103.7708}},
    }
    with TestClient(app) as client:
        conflict = client.post("/api/intent/parse", json={
            "text": "bubble tea then go Orchard MRT", **endpoints,
        }).json()
        destination_only = client.post("/api/intent/parse", json={
            "text": "go to Orchard MRT", **endpoints,
        }).json()
        nonsense = client.post("/api/intent/parse", json={
            "text": "I like cats", **endpoints,
        }).json()
        origin_conflict = client.post("/api/intent/parse", json={
            "text": "I'm starting at Orchard MRT and need coffee", **endpoints,
        }).json()

    assert conflict["status"] == "needs_clarification"
    assert conflict["intent"]["required_errands"][0]["category"] == "bubble_tea"
    assert conflict["journey_conflicts"][0]["endpoint"] == "destination"
    assert "Fajar" in conflict["journey_conflicts"][0]["current_label"]
    assert "destination" in destination_only["clarification_question"].lower()
    assert "couldn't find an errand" in nonsense["clarification_question"]
    assert origin_conflict["journey_conflicts"][0]["endpoint"] == "origin"


def test_catalog_exposes_independent_places_and_expanded_categories(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    repository = HubRepository(database)
    repository.initialize()
    ingest_payload(repository, {
        "capture_metadata": {"captured_at": "2026-08-28T00:00:00+00:00"},
        "elements": [
            {"type": "node", "id": 11, "lat": 1.33, "lon": 103.82, "tags": {"name": "Sakura Independent Kitchen", "amenity": "restaurant", "cuisine": "japanese"}},
            {"type": "node", "id": 12, "lat": 1.331, "lon": 103.821, "tags": {"name": "Neighbourhood Blooms", "shop": "florist"}},
        ],
    })
    app = create_app(Settings(onemap_mock=True, database_path=database))
    with TestClient(app) as client:
        categories = client.get("/api/catalog/categories").json()
        places = client.get("/api/catalog/search", params={"q": "Sakura", "category": "japanese_food"}).json()

    assert any(item["slug"] == "japanese_food" for item in categories)
    assert places[0]["display_name"] == "Sakura Independent Kitchen"
    assert places[0]["kind"] == "place"
    assert "source_id" not in json.dumps(places)
    assert all(raw not in json.dumps(places).casefold() for raw in ("node/", "way/", "relation/"))


def test_consumer_labels_and_detour_breakdown_never_leak_raw_ids(tmp_path: Path) -> None:
    assert safe_label("KFC · node/2577843460") == "KFC"
    assert safe_label("Mr Coconut - way/12257181530") == "Mr Coconut"
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "presentation.db"))
    with TestClient(app) as client:
        response = client.post("/api/optimize", json={
            "origin": {"query": "Punggol"}, "destination": {"query": "Orchard"},
            "errands": ["groceries", "pharmacy"],
        })
    assert response.status_code == 200
    body = response.json()
    recommendation = body["recommendations"]["best_overall"]
    assert recommendation["detour_breakdown"]["dwell_minutes"] == 30
    assert recommendation["detour_breakdown"]["total_incremental_minutes"] == recommendation["incremental_detour_minutes"]
    consumer_json = json.dumps(body["recommendations"]).casefold()
    assert all(raw not in consumer_json for raw in ("node/", "way/", "relation/", "hub_id", "source_id"))
