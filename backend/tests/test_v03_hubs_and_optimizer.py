from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.candidates import generate_candidates


def test_two_errand_generation_includes_consolidated_hubs(repository) -> None:
    candidates = generate_candidates(repository, ("groceries", "pharmacy"))
    consolidated = [candidate for candidate in candidates if candidate.consolidated]
    separate = [candidate for candidate in candidates if len(candidate.stops) == 2]

    assert consolidated
    assert separate
    assert all(len(candidate.stops) == 1 for candidate in consolidated)
    assert all(
        {"groceries", "pharmacy"}.issubset(candidate.stops[0].categories)
        for candidate in consolidated
    )


def test_hub_is_returned_once_with_both_matching_outlets(tmp_path: Path) -> None:
    settings = Settings(
        onemap_mock=True,
        database_path=tmp_path / "optimize.db",
        max_candidates=8,
        max_straight_line_detour_km=20,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/optimize",
            json={
                "origin": {"query": "Punggol"},
                "destination": {"query": "Orchard"},
                "errands": ["groceries", "pharmacy"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert "best_overall" in body["recommendations"]
    signatures = {
        tuple((stop["coordinate"]["latitude"], stop["coordinate"]["longitude"]) for stop in item["stops"])
        for item in body["recommendations"].values()
    }
    assert len(signatures) == len(body["recommendations"])
    assert body["diagnostics"]["generated_candidate_count"] > 0
    assert body["diagnostics"]["evaluated_candidate_count"] <= settings.max_candidates * 2
    assert body["diagnostics"]["routing_call_count"] > 0
    assert body["diagnostics"]["routing_call_count"] <= settings.routing_hard_budget
    assert body["diagnostics"]["cache_hit_count"] >= 0
    assert body["diagnostics"]["provider_latency_ms"] >= 0
    assert body["diagnostics"]["optimization_latency_ms"] >= 0
    assert any(item["consolidated"] for item in body["recommendations"].values())

    for recommendation in body["recommendations"].values():
        assert recommendation["dwell_minutes"] == 30
        assert recommendation["routed_segment_count"] >= 2
        assert recommendation["stop_relationship"]
        assert recommendation["explanation"]
        assert all(stop["semantic_type"] for stop in recommendation["stops"])
        if recommendation["consolidated"]:
            assert len(recommendation["stops"]) == 1
            outlets = " ".join(recommendation["stops"][0]["matching_outlets"])
            assert "groceries" in outlets
            assert "pharmacy" in outlets


def test_api_rejects_more_than_two_errands(tmp_path: Path) -> None:
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "limit.db"))
    with TestClient(app) as client:
        response = client.post(
            "/api/optimize",
            json={
                "origin": {"query": "Punggol"},
                "destination": {"query": "Orchard"},
                "errands": ["groceries", "pharmacy", "parcel"],
            },
        )
    assert response.status_code == 422
