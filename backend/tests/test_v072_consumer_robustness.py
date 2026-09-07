from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import ScoringWeights, Settings
from app.db import HubRepository
from app.main import create_app
from app.presentation import contains_raw_identifier, hub_location_context, safe_label
from app.services.intent_parser import DeterministicIntentParser
from app.services.optimizer import calculate_score


def _intent(category: str, **updates):
    errand = {"category": category, "required": True, "substitutes_allowed": True}
    errand.update(updates.pop("errand", {}))
    return {
        "original_text": updates.pop("original_text", category),
        "required_errands": [errand],
        "preferences": updates.pop("preferences", {}),
        **updates,
    }


def test_parser_distinguishes_soft_and_strict_time_language(repository) -> None:
    parser = DeterministicIntentParser(repository)
    soft = parser.parse("Get groceries, try to keep it under 15 minutes").intent
    strict = parser.parse("Get bubble tea under 10 minutes max").intent
    assert soft and soft.preferences.max_detour_minutes == 15
    assert soft.preferences.max_detour_is_hard is False
    assert strict and strict.preferences.max_detour_minutes == 10
    assert strict.preferences.max_detour_is_hard is True


def test_internal_detour_boundary_labels_instead_of_erasing_result(tmp_path: Path) -> None:
    app = create_app(Settings(
        onemap_mock=True, database_path=tmp_path / "soft-boundary.db",
        max_reasonable_detour_minutes=0.1,
    ))
    with TestClient(app) as client:
        body = client.post("/api/optimize", json={
            "origin": {"query": "Punggol"}, "destination": {"query": "Orchard"},
            "errands": ["groceries"],
        }).json()
    assert body["recommendations"]
    assert body["outcome"] == "best_available"
    assert body["recommendations"]["best_overall"]["quality_label"] == "Best available"


def test_strict_limit_is_not_presented_as_satisfied(tmp_path: Path) -> None:
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "strict.db"))
    with TestClient(app) as client:
        body = client.post("/api/optimize-intent", json={
            "origin": {"query": "Punggol"}, "destination": {"query": "Orchard"},
            "intent": _intent("groceries", preferences={
                "max_detour_minutes": 0, "max_detour_is_hard": True,
            }),
        }).json()
    closest = body["recommendations"]["best_overall"]
    assert body["outcome"] == "closest_option"
    assert closest["match_classification"] == "exceeds_limit"
    assert closest["hard_constraints_satisfied"] is False
    assert closest["quality_label"] == "Closest option"


def test_preferred_brand_can_relax_but_required_brand_never_substitutes(tmp_path: Path) -> None:
    database = tmp_path / "brands.db"
    repository = HubRepository(database)
    repository.initialize()
    hubs = [
        {"name": "Far KFC", "latitude": 1.3533, "longitude": 103.9451, "semantic_type": "standalone", "transport_area_id": None, "consolidation_group_id": "far", "source": "test", "source_id": "hub/kfc", "last_verified_at": None, "opening_hours": None, "closure_status": "open", "transport_node_distance_m": None, "address": "10 Tampines Central"},
        {"name": "Easy Chicken", "latitude": 1.3850, "longitude": 103.7446, "semantic_type": "station_area", "transport_area_id": None, "consolidation_group_id": "easy", "source": "test", "source_id": "hub/easy", "last_verified_at": None, "opening_hours": None, "closure_status": "open", "transport_node_distance_m": None, "address": "20 Choa Chu Kang Avenue 4"},
    ]
    outlets = [
        {"hub_source_id": "hub/kfc", "name": "KFC", "brand_slug": "kfc", "categories": ("fried_chicken",), "source": "test", "source_id": "outlet/kfc", "last_verified_at": None, "opening_hours": None, "closure_status": "open"},
        {"hub_source_id": "hub/easy", "name": "Easy Chicken", "brand_slug": None, "categories": ("fried_chicken",), "source": "test", "source_id": "outlet/easy", "last_verified_at": None, "opening_hours": None, "closure_status": "open"},
    ]
    repository.replace_source_data("test", [], hubs, outlets)
    app = create_app(Settings(onemap_mock=True, database_path=database))
    base = {"origin": {"query": "Boon Lay"}, "destination": {"query": "Fajar"}}
    with TestClient(app) as client:
        preferred = client.post("/api/optimize-intent", json={**base, "intent": _intent("fried_chicken", errand={"preferred_brand": "KFC", "substitutes_allowed": True})}).json()
        required = client.post("/api/optimize-intent", json={**base, "intent": _intent("fried_chicken", errand={"exact_brand": "KFC", "substitutes_allowed": False})}).json()
    assert preferred["recommendations"]["best_overall"]["match_classification"] == "easier_alternative"
    assert preferred["recommendations"]["best_overall"]["stops"][0]["display_name"] == "Easy Chicken"
    assert all("Easy Chicken" not in json.dumps(item["businesses"]) for item in required["recommendations"]["best_overall"]["stops"])
    assert "KFC" in json.dumps(required["recommendations"]["best_overall"]["stops"])


def test_location_enrichment_always_produces_actionable_context(repository) -> None:
    hub = repository.find_for_categories(("groceries",))[0]
    location = hub_location_context(hub)
    assert location.navigation_ready
    assert location.context
    assert "unavailable" not in location.context.casefold()


def test_data_quality_is_a_small_configurable_tie_break() -> None:
    weights = ScoringWeights(data_quality_bonus=2.5)
    unclear = calculate_score(7, 0, 0, weights, data_quality_score=0.5)
    clear = calculate_score(8, 0, 0, weights, data_quality_score=0.95)
    much_slower = calculate_score(12, 0, 0, weights, data_quality_score=1.0)
    assert clear < unclear
    assert much_slower > unclear


def test_catalog_search_is_unified_and_bounded(tmp_path: Path) -> None:
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "catalog.db"))
    with TestClient(app) as client:
        results = client.get("/api/catalog/search", params={"q": "pharmacy", "limit": 5}).json()
    assert len(results) <= 5
    assert any(item["kind"] == "category" and item["categories"] == ["pharmacy"] for item in results)
    assert not any(contains_raw_identifier(item["display_name"]) for item in results)


def test_consumer_label_strips_raw_source_identifier() -> None:
    cleaned = safe_label("Pharmacy node/12486727562")
    assert cleaned == "Pharmacy"
    assert not contains_raw_identifier(cleaned)
