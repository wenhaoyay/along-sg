"""A brand the person ruled out never serves their errand: its stores are
taken out of the hubs before candidates are built, so a hub only counts for
a category through the stores that are left."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import Coordinate, Hub, Store
from app.intent_models import IntentErrand, IntentV1
from app.main import create_app
from app.services.candidates import BrandExcludingRepository, exclude_brand_stores
from app.services.intent_parser import IntentParserService


def test_a_brand_cannot_be_both_wanted_and_excluded():
    with pytest.raises(ValueError):
        IntentErrand(category="pharmacy", exact_brand="Watsons", substitutes_allowed=False,
                     excluded_brands=["Watsons"])


def test_validation_keeps_exclusions_and_accepts_fast_food(repository):
    intent = IntentV1(
        original_text="fast food but not McDonald's",
        required_errands=[IntentErrand(category="fast_food", excluded_brands=["mcd", "Unknown Burger Co"])],
    )
    canonical, unresolved = IntentParserService(repository).validate_intent(intent)
    assert unresolved == []
    # Catalog names where the brand is known; anything else kept as typed.
    assert canonical.required_errands[0].excluded_brands == ["McDonald's", "Unknown Burger Co"]


def _hub(hub_id: int, *stores: Store) -> Hub:
    return Hub(hub_id, f"Hub {hub_id}", Coordinate(1.3, 103.8), stores)


def test_a_hub_qualifies_only_through_stores_that_are_not_excluded():
    mcdonalds = Store("McDonald's", "fast_food", "McDonald's", ("burgers",))
    mos = Store("MOS Burger", "fast_food", None, ("burgers",))
    guardian = Store("Guardian", "pharmacy", "Guardian")
    only_mcdonalds = _hub(1, mcdonalds, guardian)
    both = _hub(2, mcdonalds, mos)
    nothing_left = _hub(3, mcdonalds)
    kept = exclude_brand_stores([only_mcdonalds, both, nothing_left], frozenset({"McDonald's"}))
    assert [hub.id for hub in kept] == [1, 2]
    assert "fast_food" not in kept[0].categories and "pharmacy" in kept[0].categories
    assert [store.name for store in kept[1].stores] == ["MOS Burger"]
    assert exclude_brand_stores([both], frozenset()) == [both]


def test_excluding_repository_filters_lookups_and_passes_the_rest(repository):
    view = BrandExcludingRepository(repository, frozenset({"Watsons"}))
    hubs = view.find_for_categories(("pharmacy",))
    assert hubs
    assert all(store.canonical_brand != "Watsons" for hub in hubs for store in hub.stores)
    assert view.brand_catalog() == repository.brand_catalog()


def test_optimised_plan_never_stops_at_an_excluded_brand(tmp_path: Path):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "exclude.db"))
    with TestClient(app) as client:
        optimized = client.post("/api/optimize-intent", json={
            "origin": {"query": "Punggol MRT"},
            "destination": {"query": "Orchard MRT"},
            "intent": {
                "schema_version": "1.0",
                "original_text": "pharmacy except Watsons",
                "required_errands": [{"category": "pharmacy", "excluded_brands": ["watsons"]}],
            },
        })
        assert optimized.status_code == 200
        body = optimized.json()
        body.pop("intent")
        assert body["recommendations"]
        assert "Watsons" not in json.dumps(body)
