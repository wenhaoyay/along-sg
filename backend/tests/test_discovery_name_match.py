"""A word found in a place's name only proves something when the word is
known to be what is wanted: for an unrecognised word it is a guess."""

from __future__ import annotations

from app.discovery_models import DiscoveryConfidence, NeedSemanticType, SemanticExpansion
from app.services.discovery import _strong_name_match


def test_unknown_word_name_matches_are_at_most_likely():
    expansion = SemanticExpansion(
        semantic_type=NeedSemanticType.UNKNOWN, canonical_term="kopi", generic_term=None,
        likely_place_types=("place",), related_search_terms=("kopi",), category_hint=None,
        confidence=DiscoveryConfidence.LIKELY,
    )
    assert not _strong_name_match(True, expansion)
    dish = SemanticExpansion(
        semantic_type=NeedSemanticType.DISH, canonical_term="laksa", generic_term="food",
        likely_place_types=("restaurant",), related_search_terms=("laksa",), category_hint="restaurants",
        confidence=DiscoveryConfidence.STRONG,
    )
    assert _strong_name_match(True, dish)
