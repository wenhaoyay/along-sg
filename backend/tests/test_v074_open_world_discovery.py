from __future__ import annotations

from pathlib import Path
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import HubRepository
from app.discovery_models import (
    DiscoveryConfidence,
    DiscoverySearchContext,
    DiscoverySource,
    EvidenceTier,
    NeedSemanticType,
    ResolvedPlace,
)
from app.domain import Coordinate
from app.main import create_app, discovery_hubs_for_intent
from app.providers.mock import MockOneMapProvider
from app.providers.place_search import (
    GeoapifyPlaceSearchProvider,
    MockLivePlaceSearchProvider,
    TomTomPlaceSearchProvider,
)
from app.providers.web_search import MockWebDiscoveryProvider, WebCandidate
from app.services.discovery import NeedResolver, web_location_hints
from app.services.open_needs import PlausibleNeedParser, open_category
from app.services.optimizer import Optimizer
from app.services.intent_optimizer import optimize_intent
from app.intent_models import IntentErrand, IntentV1


def seeded_repository(path: Path) -> HubRepository:
    repo = HubRepository(path)
    repo.initialize()
    repo.replace_source_data(
        "openstreetmap", [],
        [{
            "name": "Senja Hawker and Shops", "latitude": 1.3828, "longitude": 103.7614,
            "semantic_type": "mall", "transport_area_id": None, "consolidation_group_id": "senja",
            "source": "openstreetmap", "source_id": "senja", "last_verified_at": "2026-08-30T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown", "transport_node_distance_m": 150,
            "address": "Senja, Singapore",
        }],
        [
            {"hub_source_id": "senja", "name": "Ah Seng Mee Pok", "original_name": "Ah Seng Mee Pok",
             "alt_names": "Bak Chor Mee", "cuisine": "noodle;chinese", "shop": None, "amenity": "restaurant",
             "search_metadata": "mee pok minced meat noodles", "brand_slug": None,
             "categories": ("chinese_food", "restaurants"), "source": "openstreetmap", "source_id": "food/1",
             "last_verified_at": "2026-08-30T00:00:00+00:00", "opening_hours": None, "closure_status": "unknown"},
            {"hub_source_id": "senja", "name": "Guardian", "original_name": "Guardian", "alt_names": None,
             "cuisine": None, "shop": "chemist", "amenity": "pharmacy", "search_metadata": "pharmacy medicine",
             "brand_slug": "guardian", "categories": ("pharmacy",), "source": "openstreetmap", "source_id": "shop/1",
             "last_verified_at": "2026-08-30T00:00:00+00:00", "opening_hours": None, "closure_status": "unknown"},
        ],
    )
    return repo


def test_http_client_request_urls_are_not_logged_at_info() -> None:
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_spatial_shortlist_preserves_both_needs(tmp_path: Path) -> None:
    from app.domain import Hub, RouteResult, Store
    from app.services.candidates import staged_candidate_pipeline

    repository = HubRepository(tmp_path / "coverage.db")
    repository.initialize()
    origin, destination = Coordinate(1.38, 103.76), Coordinate(1.30, 103.83)
    hubs = (
        Hub(-1, "Near pharmacy", destination, (Store("Pharmacy", "open_medicine"),)),
        Hub(-2, "Food stop", Coordinate(1.30, 103.86), (Store("Noodles", "open_food"),)),
    )
    pipeline = staged_candidate_pipeline(
        repository, ("open_medicine", "open_food"), origin, destination,
        RouteResult(30, 5, 300, 1), 4, 12, extra_hubs=hubs,
    )
    assert pipeline.candidates
    assert all(set(option.required_categories) == {"open_medicine", "open_food"}
               for option in pipeline.candidates)


def test_plausible_open_need_and_compound_parsing() -> None:
    parser = PlausibleNeedParser()
    needs = parser.parse("Meepok and panadol")
    assert [item.normalized_text for item in needs] == ["meepok", "panadol"]
    assert needs[0].inferred_type == NeedSemanticType.DISH
    assert needs[1].inferred_type == NeedSemanticType.PRODUCT
    assert parser.parse("dinosaur nuggets")[0].resolution_status.value == "open"
    assert parser.parse("KFC")[0].inferred_type == NeedSemanticType.SPECIFIC_BUSINESS
    assert parser.parse("McDonald's")[0].inferred_type == NeedSemanticType.SPECIFIC_BUSINESS
    assert parser.parse("I like cats") == ()
    assert parser.parse("tell me a joke") == ()


@pytest.mark.asyncio
async def test_product_semantics_never_claim_inventory(tmp_path: Path) -> None:
    result = await NeedResolver(seeded_repository(tmp_path / "product.db")).resolve("Panadol", allow_live=False)
    assert result.semantic_type == NeedSemanticType.PRODUCT
    assert result.places
    assert all(place.suitability == "category_likely" for place in result.places)
    assert "stock is not guaranteed" in result.warnings[0]


@pytest.mark.asyncio
async def test_dish_requires_direct_evidence(tmp_path: Path) -> None:
    generic = ResolvedPlace(
        display_name="Generic Chinese Restaurant", coordinate=Coordinate(1.30, 103.84),
        category="Chinese restaurant", source=DiscoverySource.MOCK_LIVE,
        confidence=DiscoveryConfidence.LIKELY, evidence=("restaurant", "noodles"),
    )
    resolver = NeedResolver(
        HubRepository(tmp_path / "empty.db"),
        MockLivePlaceSearchProvider({"mee pok": [generic]}),
    )
    resolver.repository.initialize()
    result = await resolver.resolve("mee pok")
    assert result.places == ()
    assert result.clarification == "We couldn't find a reliable place for 'mee pok'."


@pytest.mark.asyncio
async def test_dish_match_does_not_accept_longer_geographic_word(tmp_path: Path) -> None:
    malan_road = ResolvedPlace(
        display_name="Malan Road", coordinate=Coordinate(1.2775, 103.8031),
        address="Malan Road, Singapore", category="street",
        source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.LIKELY,
        evidence=("street",),
    )
    resolver = NeedResolver(
        HubRepository(tmp_path / "mala-prefix.db"),
        MockLivePlaceSearchProvider({"mala": [malan_road]}),
    )
    resolver.repository.initialize()
    result = await resolver.resolve("mala")
    assert result.places == ()


@pytest.mark.asyncio
async def test_provider_category_alias_accepts_photo_lab_for_passport_photo(tmp_path: Path) -> None:
    photo_booth = ResolvedPlace(
        display_name="Photo-Me", coordinate=Coordinate(1.3002, 103.8454),
        address="60B Orchard Road, Singapore", category="photo lab/development",
        source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.LIKELY,
        evidence=("photo lab/development",),
    )
    resolver = NeedResolver(
        HubRepository(tmp_path / "photo-alias.db"),
        MockLivePlaceSearchProvider({"passport photo": [photo_booth]}),
        primary_calls_per_need=1,
    )
    resolver.repository.initialize()
    result = await resolver.resolve("passport photo")
    assert result.places[0].display_name == "Photo-Me"


@pytest.mark.asyncio
async def test_web_business_grounding_drops_route_geometry(tmp_path: Path) -> None:
    class CorridorSensitiveProvider(MockLivePlaceSearchProvider):
        async def search(self, query, limit=8, context=None, category_hint=None):
            self._calls += 1
            if context and context.route_geometry:
                return []
            return self.fixtures.get(" ".join(query.casefold().split()), [])[:limit]

    soxxi = ResolvedPlace(
        display_name="Soxxi Master", coordinate=Coordinate(1.3489, 103.8408),
        address="37 Jalan Pemimpin, Singapore", category="shop",
        source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.LIKELY,
        evidence=("shop",),
    )
    provider = CorridorSensitiveProvider({"soxxi master": [soxxi]})
    web = MockWebDiscoveryProvider({"key duplication": [WebCandidate(
        "Soxxi Master | Key Duplication Specialist", "https://example.test", "Singapore",
    )]})
    resolver = NeedResolver(
        HubRepository(tmp_path / "grounding-context.db"), provider,
        web_provider=web, primary_calls_per_need=1, grounding_candidate_limit=1,
    )
    resolver.repository.initialize()
    result = await resolver.resolve(
        "key duplication",
        context=DiscoverySearchContext(route_geometry=(
            Coordinate(1.38, 103.76), Coordinate(1.30, 103.83),
        )),
    )
    assert result.places[0].display_name == "Soxxi Master"
    assert result.places[0].source == DiscoverySource.WEB_GROUNDED


@pytest.mark.asyncio
async def test_mall_only_grounding_cannot_be_presented_as_a_named_outlet(tmp_path: Path) -> None:
    orchard_central = ResolvedPlace(
        display_name="Orchard Central", coordinate=Coordinate(1.3007, 103.8402),
        address="181 Orchard Road, Singapore", category="shopping center",
        source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.LIKELY,
        evidence=("shopping center",),
    )
    provider = MockLivePlaceSearchProvider({"orchard central": [orchard_central]})
    web = MockWebDiscoveryProvider({"molly tea": [WebCandidate(
        "Molly Tea Singapore Review", "https://example.test",
        "Molly Tea has officially landed at Orchard Central in Singapore.",
    )]})
    resolver = NeedResolver(
        HubRepository(tmp_path / "web-location.db"), provider,
        web_provider=web, primary_calls_per_need=1, grounding_candidate_limit=1,
    )
    resolver.repository.initialize()
    result = await resolver.resolve("Molly Tea")
    assert not result.places


def test_web_location_hints_reject_language_word_but_keep_mall() -> None:
    hints = web_location_hints(
        "Molly Tea landed in Orchard Central – it is called mo li in Mandarin."
    )
    assert "Orchard Central" in hints
    assert "Mandarin" not in hints


@pytest.mark.asyncio
async def test_generic_web_lead_cannot_become_a_routable_place(tmp_path: Path) -> None:
    singapore = ResolvedPlace(
        display_name="Singapore", coordinate=Coordinate(1.2894, 103.85),
        address="Singapore", source=DiscoverySource.MOCK_LIVE,
        confidence=DiscoveryConfidence.LIKELY,
    )
    provider = MockLivePlaceSearchProvider({"singapore": [singapore]})
    web = MockWebDiscoveryProvider({"key duplication": [WebCandidate(
        "Singapore | Key Duplication Guide", "https://example.test", "Find a key service.",
    )]})
    resolver = NeedResolver(
        HubRepository(tmp_path / "generic-web-lead.db"), provider,
        web_provider=web, primary_calls_per_need=1, grounding_candidate_limit=1,
    )
    resolver.repository.initialize()
    result = await resolver.resolve("key duplication")
    assert result.places == ()


@pytest.mark.asyncio
async def test_provider_ladder_and_web_grounding(tmp_path: Path) -> None:
    grounded = ResolvedPlace(
        display_name="Molly Tea", coordinate=Coordinate(1.3002, 103.8391),
        address="Orchard Road, Singapore", category="bubble tea", source=DiscoverySource.MOCK_LIVE,
        confidence=DiscoveryConfidence.LIKELY, evidence=("bubble tea",),
    )
    primary = MockLivePlaceSearchProvider({"molly tea": []})
    secondary = MockLivePlaceSearchProvider({"molly tea": []})
    web = MockWebDiscoveryProvider({"molly tea": [WebCandidate("Molly Tea - Singapore", "https://example.test/molly", "Molly Tea outlet") ]})
    primary.fixtures["molly tea"] = []
    primary.fixtures["molly tea singapore"] = []
    secondary.fixtures["molly tea"] = [grounded]
    result = await NeedResolver(
        seeded_repository(tmp_path / "ladder.db"), primary,
        secondary_provider=secondary, web_provider=web,
    ).resolve("Molly Tea")
    assert result.places[0].display_name == "Molly Tea"
    assert result.provider_calls["mock_live"] <= 3


@pytest.mark.asyncio
async def test_web_result_without_coordinate_grounding_is_discarded(tmp_path: Path) -> None:
    web = MockWebDiscoveryProvider({"mystery shop": [WebCandidate("Mystery Shop", "https://example.test", "Singapore") ]})
    resolver = NeedResolver(
        seeded_repository(tmp_path / "web.db"), MockLivePlaceSearchProvider(),
        web_provider=web,
    )
    result = await resolver.resolve("Mystery Shop")
    assert result.web_fallback_used is True
    assert result.places == ()
    assert result.grounding_calls == 1


def test_compound_api_creates_two_open_needs_and_rejects_nonsense(tmp_path: Path) -> None:
    app = create_app(Settings(
        onemap_mock=True, database_path=tmp_path / "api.db",
        analytics_database_path=tmp_path / "analytics.db",
    ))
    with TestClient(app) as client:
        seeded_repository(tmp_path / "api.db")
        response = client.post("/api/intent/parse", json={
            "text": "Meepok and panadol",
            "origin": {"label": "Senja LRT Station", "coordinate": {"latitude": 1.3828, "longitude": 103.7624}},
            "destination": {"label": "Orchard MRT Station", "coordinate": {"latitude": 1.3043, "longitude": 103.8322}},
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "resolved"
        errands = body["intent"]["required_errands"]
        assert len(errands) == 2
        assert [item["open_need"]["inferred_type"] for item in errands] == ["dish", "product"]
        assert all(item["category"].startswith("open_") for item in errands)
        assert "couldn't find an errand" not in str(body).casefold()
        nonsense = client.post("/api/intent/parse", json={"text": "I like cats"}).json()
        assert nonsense["status"] == "unresolved"


@pytest.mark.asyncio
async def test_same_mall_open_needs_consolidate_to_one_hub(tmp_path: Path) -> None:
    repo = seeded_repository(tmp_path / "hub.db")
    resolver = NeedResolver(repo)
    food = await resolver.resolve("meepok", allow_live=False)
    medicine = await resolver.resolve("panadol", allow_live=False)
    intent = IntentV1(
        original_text="meepok and panadol",
        required_errands=[
            IntentErrand(category=open_category("meepok"), discovery_concept="meepok", open_need=food.open_need, discovery_category=food.category),
            IntentErrand(category=open_category("panadol", 1), discovery_concept="panadol", open_need=medicine.open_need, discovery_category=medicine.category),
        ],
    )
    hubs = await discovery_hubs_for_intent(resolver, intent, [], DiscoverySearchContext())
    consolidated = next(hub for hub in hubs if len(hub.stores) == 2)
    assert consolidated.name == "Senja Hawker and Shops"
    assert consolidated.semantic_type == "mall"


@pytest.mark.asyncio
async def test_two_open_needs_reach_bounded_optimizer(tmp_path: Path) -> None:
    repo = seeded_repository(tmp_path / "open-optimize.db")
    resolver = NeedResolver(repo)
    food = await resolver.resolve("meepok", allow_live=False)
    medicine = await resolver.resolve("panadol", allow_live=False)
    intent = IntentV1(
        original_text="meepok and panadol",
        required_errands=[
            IntentErrand(category=open_category("meepok"), discovery_concept="meepok", open_need=food.open_need, discovery_category=food.category),
            IntentErrand(category=open_category("panadol", 1), discovery_concept="panadol", open_need=medicine.open_need, discovery_category=medicine.category),
        ],
    )
    hubs = await discovery_hubs_for_intent(resolver, intent, [], DiscoverySearchContext())
    optimizer = Optimizer(MockOneMapProvider(), repo, Settings().scoring, 4, 12)
    _, recommendations, diagnostics, categories = await optimize_intent(
        optimizer, Coordinate(1.3828, 103.7624), Coordinate(1.3043, 103.8322), intent, None, hubs,
    )
    assert categories == [open_category("meepok"), open_category("panadol", 1)]
    assert recommendations["best_overall"].option.consolidated is True
    assert diagnostics["routing_call_count"] <= 12


@pytest.mark.asyncio
async def test_route_context_is_reused_by_optimizer_cache(tmp_path: Path) -> None:
    repo = seeded_repository(tmp_path / "route.db")
    provider = MockOneMapProvider()
    optimizer = Optimizer(provider, repo, Settings().scoring, 4, 12)
    origin, destination = Coordinate(1.3828, 103.7624), Coordinate(1.3043, 103.8322)
    context, calls, _ = await optimizer.prepare_discovery_context(origin, destination)
    assert calls == 1
    assert len(context.route_geometry) >= 2
    _, second_calls, _ = await optimizer.prepare_discovery_context(origin, destination)
    assert second_calls == 0


def test_provider_schema_normalizers_cover_tomtom_and_geoapify() -> None:
    tomtom = TomTomPlaceSearchProvider._normalize({"results": [{
        "id": "x", "poi": {"name": "Molly Tea", "categories": ["tea shop"]},
        "address": {"freeformAddress": "Orchard, Singapore"}, "position": {"lat": 1.3, "lon": 103.84},
    }]})
    assert tomtom[0].source == DiscoverySource.TOMTOM
    assert tomtom[0].evidence_tier == EvidenceTier.SUPPORTED


@pytest.mark.asyncio
async def test_geoapify_adapter_restricts_search_to_singapore() -> None:
    provider = GeoapifyPlaceSearchProvider("placeholder")
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"results": [{
            "name": "Photo Shop", "formatted": "Singapore", "lat": 1.31, "lon": 103.84,
            "categories": ["commercial.photo"], "place_id": "p1",
        }]})

    await provider._client.aclose()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    results = await provider.search("passport photo", context=DiscoverySearchContext(center=Coordinate(1.31, 103.84)))
    await provider.close()
    assert "filter=countrycode%3Asg" in captured["url"]
    assert results[0].source == DiscoverySource.GEOAPIFY


@pytest.mark.asyncio
async def test_tomtom_along_route_rejection_falls_back_once_to_fuzzy_search() -> None:
    provider = TomTomPlaceSearchProvider("placeholder", max_retries=0, hard_budget=2)
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(403, json={"error": "not enabled"})
        return httpx.Response(200, json={"results": [{
            "id": "mee-pok", "poi": {"name": "Guan's Mee Pok", "categories": ["chinese"]},
            "address": {"freeformAddress": "13 Stamford Road, Singapore"},
            "position": {"lat": 1.29306, "lon": 103.85129},
        }]})

    await provider._client.aclose()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    results = await provider.search("mee pok", context=DiscoverySearchContext(
        center=Coordinate(1.33, 103.80),
        route_geometry=(Coordinate(1.38, 103.76), Coordinate(1.30, 103.83)),
    ))
    await provider.close()
    assert methods == ["POST", "GET"]
    assert results[0].display_name == "Guan's Mee Pok"


@pytest.mark.asyncio
async def test_off_corridor_local_match_does_not_suppress_live_fallback(tmp_path: Path) -> None:
    repo = seeded_repository(tmp_path / "off-corridor.db")
    repo.replace_source_data(
        "openstreetmap", [],
        [{
            "name": "Far Food", "latitude": 1.20, "longitude": 103.60,
            "semantic_type": "standalone", "transport_area_id": None,
            "consolidation_group_id": None, "source": "openstreetmap",
            "source_id": "far", "last_verified_at": "2026-08-30T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown",
            "transport_node_distance_m": 100, "address": "Far away",
        }],
        [{
            "hub_source_id": "far", "name": "Far Mee Pok", "original_name": "Far Mee Pok",
            "alt_names": None, "cuisine": "noodle", "shop": None,
            "amenity": "restaurant", "search_metadata": "mee pok",
            "brand_slug": None, "categories": ("restaurants",),
            "source": "openstreetmap", "source_id": "far/food",
            "last_verified_at": "2026-08-30T00:00:00+00:00",
            "opening_hours": None, "closure_status": "unknown",
        }],
    )
    near = ResolvedPlace(
        display_name="Near Mee Pok", coordinate=Coordinate(1.31, 103.83),
        address="Near Orchard", category="restaurant",
        source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.LIKELY,
        evidence=("mee pok",),
    )
    provider = MockLivePlaceSearchProvider({"mee pok": [near]})
    result = await NeedResolver(repo, provider, primary_calls_per_need=1).resolve(
        "mee pok", context=DiscoverySearchContext(
            route_geometry=(Coordinate(1.38, 103.76), Coordinate(1.30, 103.83)),
            origin=Coordinate(1.38, 103.76), destination=Coordinate(1.30, 103.83),
        ),
    )
    assert result.places[0].display_name == "Near Mee Pok"
    assert provider.calls == 1
