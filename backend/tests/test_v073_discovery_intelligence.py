from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import HubRepository
from app.discovery_models import DiscoveryConfidence, DiscoverySource, NeedSemanticType, ResolvedPlace
from app.domain import Coordinate
from app.main import create_app
from app.providers.mock import MockOneMapProvider
from app.providers.place_search import MockLivePlaceSearchProvider
from app.services.discovery import LocationResolver, NeedResolver


def repository(path: Path) -> HubRepository:
    repo = HubRepository(path)
    repo.initialize()
    repo.replace_source_data(
        "openstreetmap",
        [],
        [
            {"name":"Teck Whye Market","latitude":1.381,"longitude":103.752,"semantic_type":"standalone","transport_area_id":None,"consolidation_group_id":"market","source":"openstreetmap","source_id":"market","last_verified_at":"2026-08-26T00:00:00+00:00","opening_hours":None,"closure_status":"unknown","transport_node_distance_m":500,"address":"143 Teck Whye Lane"},
            {"name":"Independent Tech Shop","latitude":1.31,"longitude":103.84,"semantic_type":"standalone","transport_area_id":None,"consolidation_group_id":"tech","source":"openstreetmap","source_id":"tech","last_verified_at":"2026-08-26T00:00:00+00:00","opening_hours":None,"closure_status":"unknown","transport_node_distance_m":400,"address":"Singapore"},
        ],
        [
            {"hub_source_id":"market","name":"Ah Hoe Mee Pok","original_name":"Ah Hoe Mee Pok","alt_names":"Ah Hoe Bak Chor Mee","cuisine":"noodle;chinese","shop":None,"amenity":"restaurant","search_metadata":"minced meat noodles","brand_slug":None,"categories":("chinese_food","restaurants"),"source":"openstreetmap","source_id":"node/1","last_verified_at":"2026-08-26T00:00:00+00:00","opening_hours":None,"closure_status":"unknown"},
            {"hub_source_id":"tech","name":"Cable Corner","original_name":"Cable Corner","alt_names":None,"cuisine":None,"shop":"electronics;mobile_phone","amenity":None,"search_metadata":"USB C phone accessories","brand_slug":None,"categories":("electronics",),"source":"openstreetmap","source_id":"node/2","last_verified_at":"2026-08-26T00:00:00+00:00","opening_hours":None,"closure_status":"unknown"},
        ],
    )
    return repo


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["Bangkit LRT", "bangkit", "bangkitlrt", "BP9", "bp 9"])
async def test_bangkit_aliases_resolve_authoritatively(tmp_path: Path, query: str) -> None:
    resolver = LocationResolver(repository(tmp_path / "places.db"), MockOneMapProvider())
    result = await resolver.resolve(query)
    assert result[0].display_name == "Bangkit LRT Station"
    assert "BP9" in (result[0].subtitle or "")
    assert result[0].source == DiscoverySource.LTA_GAZETTEER
    assert result[0].confidence == DiscoveryConfidence.EXACT


@pytest.mark.asyncio
async def test_conservative_station_typo_is_strong_not_silent_wrong_match(tmp_path: Path) -> None:
    resolver = LocationResolver(repository(tmp_path / "typo.db"), MockOneMapProvider())
    result = await resolver.resolve("Bangki LRT")
    assert result[0].display_name == "Bangkit LRT Station"
    assert result[0].confidence == DiscoveryConfidence.STRONG
    assert result[0].source == DiscoverySource.LTA_GAZETTEER


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["Choa Chu Kang", "chua chu kang", "chuachukang", "CCK", "NS4", "BP1"])
async def test_choa_chu_kang_variants_do_not_wrong_match(tmp_path: Path, query: str) -> None:
    resolver = LocationResolver(repository(tmp_path / f"{query.replace(' ', '')}.db"), MockOneMapProvider())
    result = await resolver.resolve(query)
    assert result[0].display_name.startswith("Choa Chu Kang")
    assert "Bugis" not in result[0].display_name


@pytest.mark.asyncio
async def test_local_semantic_dish_and_product_discovery(tmp_path: Path) -> None:
    resolver = NeedResolver(repository(tmp_path / "needs.db"))
    mee_pok = await resolver.resolve("meepok")
    assert mee_pok.semantic_type == NeedSemanticType.DISH
    assert mee_pok.canonical_concept == "Mee pok"
    assert mee_pok.category == "chinese_food"
    assert mee_pok.places[0].display_name == "Ah Hoe Mee Pok"
    assert "mee pok" in mee_pok.places[0].evidence
    cable = await resolver.resolve("USB-C cable")
    assert cable.semantic_type == NeedSemanticType.PRODUCT
    assert cable.places[0].display_name == "Cable Corner"


@pytest.mark.asyncio
async def test_live_fallback_trigger_and_failure_are_bounded(tmp_path: Path) -> None:
    repo = repository(tmp_path / "live.db")
    molly = ResolvedPlace(
        display_name="Molly Tea", coordinate=Coordinate(1.3001, 103.839),
        address="Singapore", category="bubble tea", source=DiscoverySource.MOCK_LIVE,
        confidence=DiscoveryConfidence.LIKELY, provenance=(DiscoverySource.MOCK_LIVE,),
    )
    live = MockLivePlaceSearchProvider({"molly tea singapore": [molly]})
    result = await NeedResolver(repo, live).resolve("Molly Tea")
    assert result.semantic_type == NeedSemanticType.SPECIFIC_BUSINESS
    assert result.live_fallback_used is True
    assert result.discovery_calls == 1
    assert result.places[0].display_name == "Molly Tea"
    high_local = await NeedResolver(repo, live).resolve("mee pok")
    assert high_local.live_fallback_used is False
    failing = await NeedResolver(repo, MockLivePlaceSearchProvider(fail=True)).resolve("Molly Tea")
    assert failing.live_provider_failed is True
    assert failing.confidence == DiscoveryConfidence.UNRESOLVED


@pytest.mark.asyncio
async def test_cross_source_deduplication_preserves_provenance(tmp_path: Path) -> None:
    repo = repository(tmp_path / "dedupe.db")
    same = ResolvedPlace(
        display_name="Ah Hoe Mee Pok", coordinate=Coordinate(1.38101, 103.75201),
        source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.LIKELY,
        provenance=(DiscoverySource.MOCK_LIVE,),
    )
    resolver = NeedResolver(repo, MockLivePlaceSearchProvider({"mee pok singapore": [same]}))
    result = await resolver.resolve("mee pok", allow_live=False)
    combined = resolver._dedupe([result.places[0], same])
    assert len(combined) == 1
    assert set(combined[0].provenance) == {DiscoverySource.OPENSTREETMAP, DiscoverySource.MOCK_LIVE}


def test_api_exposes_discovery_without_raw_provider_ids(tmp_path: Path) -> None:
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "api.db", analytics_database_path=tmp_path / "analytics.db"))
    with TestClient(app) as client:
        bangkit = client.get("/api/geocode", params={"q":"BP9"})
        assert bangkit.status_code == 200
        item = bangkit.json()["results"][0]
        assert item["label"] == "Bangkit LRT Station"
        assert item["confidence"] == "exact"
        assert "internal_id" not in item
        meepok = client.get("/api/discovery/needs", params={"q":"meepok", "live":"false"})
        assert meepok.status_code == 200
        assert meepok.json()["semantic_type"] == "dish"
        rejected = client.post("/api/intent/parse", json={"text":"I like cats"})
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "unresolved"


@pytest.mark.asyncio
async def test_gap_telemetry_is_opt_in_and_aggregate_only(tmp_path: Path) -> None:
    disabled = NeedResolver(repository(tmp_path / "disabled.db"), track_gaps=False)
    await disabled.resolve("unseen mystery errand", allow_live=False)
    assert disabled.metrics_snapshot()["unresolved_concepts"] == {}
    enabled = NeedResolver(repository(tmp_path / "enabled.db"), track_gaps=True)
    await enabled.resolve("Unseen Mystery Errand", allow_live=False)
    report = enabled.metrics_snapshot()
    assert report["unresolved_concepts"] == {"unseen mystery errand": 1}
    assert "coordinate" not in str(report).casefold()


def test_confirmed_live_coordinate_can_enter_optimizer_without_persistence(tmp_path: Path) -> None:
    database = tmp_path / "transient.db"
    app = create_app(Settings(onemap_mock=True, database_path=database, analytics_database_path=tmp_path / "analytics.db"))
    with TestClient(app) as client:
        response = client.post("/api/optimize-intent", json={
            "origin":{"coordinate":{"latitude":1.4052,"longitude":103.9024}},
            "destination":{"coordinate":{"latitude":1.3043,"longitude":103.8322}},
            "intent":{
                "schema_version":"1.0","original_text":"Molly Tea",
                "required_errands":[{"category":"bubble_tea","required":True,"substitutes_allowed":True,"discovery_concept":"Molly Tea"}],
                "optional_errands":[],"preferences":{},"parse_method":"deterministic","confidence":0.9,
            },
            "confirmed_discovery_places":[{
                "display_name":"Molly Tea","category":"bubble_tea","address":"Somerset, Singapore",
                "coordinate":{"latitude":1.3004,"longitude":103.8390},
            }],
        })
        assert response.status_code == 200
        assert response.json()["recommendations"]["best_overall"]["stops"][0]["businesses"][0]["display_name"] == "Molly Tea"
        assert client.get("/api/catalog/search", params={"q":"Molly Tea"}).json() == []
