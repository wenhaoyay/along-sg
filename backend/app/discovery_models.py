from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain import Coordinate


class DiscoveryConfidence(StrEnum):
    EXACT = "exact"
    STRONG = "strong"
    LIKELY = "likely"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class DiscoverySource(StrEnum):
    LTA_GAZETTEER = "lta_gazetteer"
    LOCAL_CATALOG = "local_catalog"
    OPENSTREETMAP = "openstreetmap"
    ONEMAP = "onemap"
    TOMTOM = "tomtom"
    GEOAPIFY = "geoapify"
    TAVILY = "tavily"
    WEB_GROUNDED = "web_grounded"
    MOCK_LIVE = "mock_live"


class NeedSemanticType(StrEnum):
    BRAND = "brand"
    SPECIFIC_BUSINESS = "specific_business"
    CATEGORY = "category"
    CUISINE = "cuisine"
    DISH = "dish"
    PRODUCT = "product"
    SERVICE = "service"
    PLACE_TYPE = "place_type"
    UNKNOWN = "unknown"


class NeedResolutionStatus(StrEnum):
    OPEN = "open"
    EXPANDED = "expanded"
    RESOLVED = "resolved"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


class EvidenceTier(StrEnum):
    VERIFIED = "verified"
    STRONG = "strong"
    SUPPORTED = "supported"
    WEAK = "weak"


class OpenNeed(BaseModel):
    """A plausible errand that remains valid without a closed taxonomy match."""

    raw_text: str = Field(min_length=1, max_length=160)
    normalized_text: str = Field(min_length=1, max_length=160)
    inferred_type: NeedSemanticType = NeedSemanticType.UNKNOWN
    known_concept_id: str | None = None
    brand_hint: str | None = None
    category_hint: str | None = None
    product_hint: str | None = None
    dish_hint: str | None = None
    service_hint: str | None = None
    hard_brand: bool = False
    optional: bool = False
    substitution_allowed: bool = True
    confidence: DiscoveryConfidence = DiscoveryConfidence.LIKELY
    resolution_status: NeedResolutionStatus = NeedResolutionStatus.OPEN
    evidence_requirements: tuple[str, ...] = ()
    related_search_terms: tuple[str, ...] = ()
    likely_place_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidatePlaceEvidence:
    source: DiscoverySource
    source_type: str
    tier: EvidenceTier
    direct_name_match: bool = False
    category_match: bool = False
    item_or_dish_match: bool = False
    address_agreement: bool = False
    coordinate_agreement: bool = False
    source_count: int = 1
    observed_text: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoverySearchContext:
    """Bounded Singapore geography shared with discovery providers."""

    center: Coordinate | None = None
    radius_m: int = 5000
    route_geometry: tuple[Coordinate, ...] = ()
    origin: Coordinate | None = None
    destination: Coordinate | None = None


@dataclass(frozen=True)
class SemanticExpansion:
    semantic_type: NeedSemanticType
    canonical_term: str
    generic_term: str | None
    likely_place_types: tuple[str, ...]
    related_search_terms: tuple[str, ...]
    category_hint: str | None = None
    confidence: DiscoveryConfidence = DiscoveryConfidence.LIKELY
    method: Literal["deterministic", "llm"] = "deterministic"
    latency_ms: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class DiscoveryConcept:
    slug: str
    display_name: str
    semantic_type: NeedSemanticType
    aliases: tuple[str, ...]
    category: str
    search_terms: tuple[str, ...]
    osm_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedLocation:
    internal_id: str
    display_name: str
    coordinate: Coordinate
    entity_type: str
    source: DiscoverySource
    confidence: DiscoveryConfidence
    address: str | None = None
    subtitle: str | None = None
    matched_alias: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedPlace:
    display_name: str
    coordinate: Coordinate
    source: DiscoverySource
    confidence: DiscoveryConfidence
    address: str | None = None
    canonical_name: str | None = None
    canonical_brand: str | None = None
    category: str | None = None
    concept: str | None = None
    mall_or_hub: str | None = None
    source_id: str | None = None
    evidence: tuple[str, ...] = ()
    provenance: tuple[DiscoverySource, ...] = ()
    structured_evidence: tuple[CandidatePlaceEvidence, ...] = ()
    evidence_tier: EvidenceTier = EvidenceTier.SUPPORTED
    suitability: Literal["business_verified", "category_likely", "inventory_verified"] = "business_verified"
    relevance_score: float = 0.0
    resolved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ResolvedNeed:
    original_query: str
    semantic_type: NeedSemanticType
    canonical_concept: str | None
    category: str | None
    confidence: DiscoveryConfidence
    source: DiscoverySource | None
    related_terms: tuple[str, ...]
    places: tuple[ResolvedPlace, ...]
    live_fallback_used: bool = False
    live_provider_failed: bool = False
    clarification: str | None = None
    discovery_calls: int = 0
    cache_hits: int = 0
    latency_ms: float = 0.0
    open_need: OpenNeed | None = None
    provider_calls: dict[str, int] = field(default_factory=dict)
    provider_latency_ms: dict[str, float] = field(default_factory=dict)
    web_fallback_used: bool = False
    grounding_calls: int = 0
    warnings: tuple[str, ...] = ()
