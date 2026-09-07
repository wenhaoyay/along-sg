from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import HubRepository
from app.main import create_app


def test_parse_preview_metrics_and_intent_optimization(tmp_path: Path):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "intent.db"))
    with TestClient(app) as client:
        parsed = client.post(
            "/api/intent/parse",
            json={"text": "Get groceries and pharmacy at one stop"},
        )
        assert parsed.status_code == 200
        preview = parsed.json()
        assert preview["status"] == "resolved"
        assert preview["intent"]["preferences"]["prefer_consolidated_stops"]

        optimized = client.post(
            "/api/optimize-intent",
            json={
                "origin": {"query": "Punggol MRT"},
                "destination": {"query": "Orchard MRT"},
                "intent": preview["intent"],
            },
        )
        assert optimized.status_code == 200
        body = optimized.json()
        assert body["intent"]["schema_version"] == "1.0"
        assert body["errands"] == ["groceries", "pharmacy"]
        assert body["diagnostics"]["routing_call_count"] <= 12
        assert all(
            rec["match_classification"] == "best_match"
            for rec in body["recommendations"].values()
        )

        metrics = client.get("/api/intent/metrics").json()
        assert metrics["total_parses"] == 1
        assert metrics["deterministic_parse_rate"] == 1


def test_optional_errand_can_be_omitted_but_required_errand_is_never_relaxed(
    tmp_path: Path,
):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "partial.db"))
    payload = {
        "origin": {"query": "Punggol MRT"},
        "destination": {"query": "Orchard MRT"},
        "intent": {
            "schema_version": "1.0",
            "original_text": "groceries, and KFC only if convenient",
            "required_errands": [{"category": "groceries", "required": True}],
            "optional_errands": [{
                "category": "fried_chicken", "required": False,
                "exact_brand": "KFC", "substitutes_allowed": False,
            }],
            "preferences": {},
            "parse_method": "deterministic",
            "confidence": 1,
        },
    }
    with TestClient(app) as client:
        response = client.post("/api/optimize-intent", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["errands"] == ["groceries"]
        assert body["recommendations"]
        assert body["diagnostics"]["routing_call_count"] <= 12
        assert all(
            rec["match_classification"] == "partial_option"
            for rec in body["recommendations"].values()
        )

        payload["intent"]["required_errands"] = [
            {
                "category": "fried_chicken", "required": True,
                "exact_brand": "KFC", "substitutes_allowed": False,
            }
        ]
        payload["intent"]["optional_errands"] = []
        hard = client.post("/api/optimize-intent", json=payload).json()
        assert hard["recommendations"] == {}
        assert hard["outcome"] == "no_practical_match"


def test_unknown_catalog_term_requires_correction(tmp_path: Path):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "unknown.db"))
    with TestClient(app) as client:
        response = client.post(
            "/api/optimize-intent",
            json={
                "origin": {"query": "Punggol MRT"},
                "destination": {"query": "Orchard MRT"},
                "intent": {
                    "original_text": "find unicorn supplies",
                    "required_errands": [{"category": "unicorn_supplies"}],
                },
            },
        )
    assert response.status_code == 422
    assert "unicorn_supplies" in response.json()["detail"]["unresolved_terms"]


def test_soft_limit_returns_the_closest_actionable_option(tmp_path: Path):
    database_path = tmp_path / "near-miss.db"
    repository = HubRepository(database_path)
    repository.initialize()
    repository.replace_source_data(
        "near-miss-test",
        [],
        [{
            "name": "Test convenience stop", "latitude": 1.35,
            "longitude": 103.85, "semantic_type": "standalone",
            "transport_area_id": None, "consolidation_group_id": "near-miss",
            "source": "near-miss-test", "source_id": "hub/1",
            "last_verified_at": None, "opening_hours": None,
            "closure_status": "open", "transport_node_distance_m": 100,
        }],
        [{
            "hub_source_id": "hub/1", "name": "Test convenience",
            "brand_slug": None, "categories": ("convenience",),
            "source": "near-miss-test", "source_id": "outlet/1",
            "last_verified_at": None, "opening_hours": None,
            "closure_status": "open",
        }],
    )
    app = create_app(Settings(onemap_mock=True, database_path=database_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/optimize-intent",
            json={
                "origin": {"query": "Punggol MRT"},
                "destination": {"query": "Orchard MRT"},
                "intent": {
                    "original_text": "pharmacy only if it adds no time",
                    "required_errands": [
                        {
                            "category": "pharmacy", "required": True,
                            "substitutes_allowed": True,
                        }
                    ],
                    "preferences": {"max_detour_minutes": 0},
                },
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]
    assert body["recommendations"]["best_overall"]["match_classification"] == "closest_exact"
    assert body["recommendations"]["best_overall"]["hard_constraints_satisfied"] is True
    assert body["near_misses"] == []
