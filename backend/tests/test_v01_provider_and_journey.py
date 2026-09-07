from __future__ import annotations

import json
from pathlib import Path

import pytest
import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.base import ProviderError
from app.providers.onemap import OneMapTokenManager, normalize_public_transport_response


def test_pt_schema_template_normalizes_to_internal_route_result() -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "onemap_pt_schema_template.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = normalize_public_transport_response(fixture["response"])

    assert result.duration_minutes == 42.0
    assert result.walking_minutes == 8.0
    assert result.walking_distance_m == 620.5
    assert result.transfers == 1
    assert [leg.mode for leg in result.legs] == ["WALK", "SUBWAY", "WALK"]


def test_pt_normalizer_rejects_unknown_shape() -> None:
    with pytest.raises(ProviderError, match="route plan"):
        normalize_public_transport_response({"unexpected": []})


async def test_token_manager_caches_and_refreshes_after_invalidation() -> None:
    calls = 0

    def auth_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"access_token": f"token-{calls}", "expiry_timestamp": "4102444800"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(auth_handler)) as client:
        tokens = OneMapTokenManager(client, "https://example.test", "email", "password")
        assert await tokens.get_token() == "token-1"
        assert await tokens.get_token() == "token-1"
        assert calls == 1
        tokens.invalidate()
        assert await tokens.get_token() == "token-2"
        assert calls == 2


def test_mock_geocode_and_baseline_journey_api(tmp_path: Path) -> None:
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "journey.db"))
    with TestClient(app) as client:
        geocode = client.get("/api/geocode", params={"q": "Punggol"})
        assert geocode.status_code == 200
        assert geocode.json()["results"][0]["label"] == "Punggol MRT"

        journey = client.post(
            "/api/journey",
            json={
                "origin": {"query": "Punggol"},
                "destination": {"query": "Orchard"},
            },
        )
        assert journey.status_code == 200
        body = journey.json()
        assert body["route"]["provider"] == "onemap-mock"
        assert body["route"]["duration_minutes"] > 0
        assert body["route"]["walking_minutes"] > 0
