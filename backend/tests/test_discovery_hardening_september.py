from pathlib import Path

import pytest

from app.db import HubRepository
from app.discovery_models import DiscoveryConfidence, DiscoverySearchContext, DiscoverySource, ResolvedPlace, SemanticExpansion, NeedSemanticType
from app.domain import Coordinate
from app.providers.place_search import MockLivePlaceSearchProvider
from app.providers.web_search import WebCandidate
from app.services.discovery import NeedResolver


def place(name, lat, lon, address='Singapore'):
    return ResolvedPlace(display_name=name, coordinate=Coordinate(lat, lon), address=address,
                         source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.STRONG,
                         category='pharmacy', evidence=('pharmacy',), relevance_score=1.0)


@pytest.mark.asyncio
async def test_response_limit_applied_after_route_distance_ranking(tmp_path, monkeypatch):
    repo = HubRepository(tmp_path / 'ranking.db'); repo.initialize()
    resolver = NeedResolver(repo)
    pool_sizes = []
    def local(expansion, concept, limit):
        pool_sizes.append(limit)
        return [place('A far pharmacy', 1.32, 103.85), place('Z near pharmacy', 1.34, 103.85)]
    monkeypatch.setattr(resolver, '_local_places', local)
    result = await resolver.resolve('Panadol', limit=1, allow_live=False,
        context=DiscoverySearchContext(route_geometry=(Coordinate(1.34, 103.80), Coordinate(1.34, 103.90))))
    assert result.places[0].display_name == 'Z near pharmacy'
    assert pool_sizes == [8]
    assert result.discovery_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('address,accepted', [('181 Orchard Road, Singapore', True), ('10 Jurong Road, Singapore', False)])
async def test_web_address_must_agree_with_named_business(tmp_path: Path, address, accepted):
    provider = MockLivePlaceSearchProvider({'molly tea': [place('Molly Tea', 1.30, 103.84, address)]})
    repo = HubRepository(tmp_path / 'web.db'); repo.initialize()
    resolver = NeedResolver(repo, provider)
    expansion = SemanticExpansion(semantic_type=NeedSemanticType.SPECIFIC_BUSINESS, canonical_term='Molly Tea',
        generic_term=None, likely_place_types=(), related_search_terms=('Molly Tea',), category_hint=None,
        confidence=DiscoveryConfidence.LIKELY)
    result = await resolver._ground_web([WebCandidate('Molly Tea', 'https://example.test/outlet',
        'Molly Tea at 181 Orchard Road, Singapore.')], expansion, None, 4)
    assert bool(result) is accepted
