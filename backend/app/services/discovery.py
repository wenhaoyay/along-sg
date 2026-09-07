from __future__ import annotations

import difflib
import json
import logging
import re
import time
from collections import Counter
from dataclasses import replace as dataclass_replace
from pathlib import Path

import httpx

from app.db import HubRepository
from app.discovery_models import (
    CandidatePlaceEvidence, DiscoveryConcept, DiscoveryConfidence, DiscoverySearchContext,
    DiscoverySource, EvidenceTier, NeedResolutionStatus, NeedSemanticType, OpenNeed,
    ResolvedLocation, ResolvedNeed, ResolvedPlace, SemanticExpansion,
)
from app.domain import Coordinate
from app.poi_taxonomy import normalize_text
from app.providers.base import MapProvider, ProviderError
from app.providers.place_search import LivePlaceSearchError, LivePlaceSearchProvider
from app.providers.semantic_expansion import SemanticExpansionProvider
from app.providers.web_search import WebCandidate, WebDiscoveryError, WebDiscoveryProvider
from app.providers.mock import haversine_km
from app.services.open_needs import PlausibleNeedParser, deterministic_expansion
from app.services.candidates import distance_to_geometry_km


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
logger = logging.getLogger("along.discovery")

PROVIDER_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "photo shop": ("photo lab", "photography", "photo booth"),
    "hair salon": ("hairdresser", "barber", "beauty salon"),
    "parcel service": ("post office", "postal", "courier"),
    "pet supplies": ("pet shop", "animal services"),
    "phone accessories": ("electronics", "computer", "mobile phone"),
    "printer supplies": ("printer", "toner", "cartridge", "computer shop"),
    "party supplies": ("party", "variety store"),
    "locksmith": ("key cutting", "key duplication", "locksmith"),
}


def compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def contains_normalized_phrase(text: str, term: str) -> bool:
    """Match a normalized term on token boundaries, not as a word prefix.

    This prevents live geocoder results such as ``Malan Road`` from satisfying
    the dish request ``mala`` while preserving punctuation variants like
    ``USB-C``/``USB C``.
    """

    normalized_text = normalize_text(text)
    normalized_term = normalize_text(term)
    return bool(normalized_term) and f" {normalized_term} " in f" {normalized_text} "


def provider_category_terms(expansion: SemanticExpansion) -> tuple[str, ...]:
    seeds = tuple(dict.fromkeys((*expansion.likely_place_types, expansion.category_hint or "")))
    terms: list[str] = []
    for seed in seeds:
        normalized = normalize_text(seed)
        if not normalized:
            continue
        terms.append(normalized)
        terms.extend(PROVIDER_CATEGORY_ALIASES.get(normalized, ()))
    return tuple(dict.fromkeys(terms))


def context_relevant(place: ResolvedPlace, context: DiscoverySearchContext | None) -> bool:
    if context is None or not context.route_geometry:
        return True
    route_distance = distance_to_geometry_km(place.coordinate, context.route_geometry)
    endpoint_distance = min(
        (
            haversine_km(place.coordinate, endpoint)
            for endpoint in (context.origin, context.destination)
            if endpoint is not None
        ),
        default=float("inf"),
    )
    return route_distance <= 2.5 or endpoint_distance <= 2.0


def web_location_hints(text: str) -> tuple[str, ...]:
    """Extract conservative, provider-groundable Singapore location phrases."""

    hints: list[str] = []
    address = re.search(
        r"\b\d{1,4}[A-Za-z]?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\s+"
        r"(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Way)\b",
        text,
    )
    if address:
        hints.append(address.group(0))
    for match in re.finditer(
        r"\b(?:at|in)\s+([A-Z][A-Za-z0-9@'&.-]+(?:\s+[A-Z][A-Za-z0-9@'&.-]+){0,2}?)"
        r"(?=\s+(?:in|at|on|with|and|where|Singapore|store|outlet)\b|\s*[,.–—\ufffd-])",
        text,
    ):
        hint = match.group(1).strip()
        if (
            len(normalize_text(hint).split()) >= 2
            and normalize_text(hint) not in {"singapore", "southeast asia"}
        ):
            hints.append(hint)
    return tuple(dict.fromkeys(hints))[:2]


def _station_alias_keys(value: str) -> set[str]:
    normal = normalize_text(value)
    compact = compact_text(value)
    keys = {normal, compact}
    code = re.fullmatch(r"([a-z]{1,3})\s*(\d{1,2})", normal)
    if code:
        keys.add(f"{code.group(1)}{code.group(2)}")
    return {item for item in keys if item}


class LocationResolver:
    def __init__(self, repository: HubRepository, provider: MapProvider, gazetteer_path: Path | None = None):
        self.repository = repository
        self.provider = provider
        payload = json.loads((gazetteer_path or DATA_DIR / "singapore-transit-gazetteer.json").read_text(encoding="utf-8"))
        self.source_metadata = payload["source"]
        self.stations = payload["stations"]
        self.alias_index: dict[str, list[tuple[dict, str]]] = {}
        for station in self.stations:
            for alias in station["aliases"]:
                for key in _station_alias_keys(alias):
                    self.alias_index.setdefault(key, []).append((station, alias))

    def _station_result(self, station: dict, confidence: DiscoveryConfidence, alias: str | None = None) -> ResolvedLocation:
        codes = " / ".join(station["station_codes"])
        lines = " · ".join(station["lines"])
        subtitle = " · ".join(item for item in (codes, lines) if item)
        return ResolvedLocation(
            internal_id=station["id"], display_name=station["canonical_name"],
            coordinate=Coordinate(station["latitude"], station["longitude"]),
            entity_type=station["entity_type"], source=DiscoverySource.LTA_GAZETTEER,
            confidence=confidence, subtitle=subtitle or None, matched_alias=alias,
            aliases=tuple(station["aliases"]),
        )

    async def resolve(self, query: str, limit: int = 6) -> list[ResolvedLocation]:
        keys = _station_alias_keys(query)
        exact: dict[str, tuple[dict, str]] = {}
        for key in keys:
            for station, alias in self.alias_index.get(key, []):
                exact[station["id"]] = (station, alias)
        if exact:
            bare_station_name = all(
                compact_text(query) == compact_text(item[0]["base_name"])
                for item in exact.values()
            )
            local_ambiguities = tuple(
                item for item in (self.repository.search_hubs(query, limit) if bare_station_name else ())
                if compact_text(item["name"]) == compact_text(query)
            )
            if local_ambiguities:
                station_results = [self._station_result(item[0], DiscoveryConfidence.AMBIGUOUS, item[1]) for item in exact.values()]
                local_results = [ResolvedLocation(
                    internal_id=f"local-hub-{item['id']}", display_name=item["name"],
                    coordinate=Coordinate(item["latitude"], item["longitude"]),
                    entity_type=item["semantic_type"], source=DiscoverySource.LOCAL_CATALOG,
                    confidence=DiscoveryConfidence.AMBIGUOUS, address=item["address"],
                    subtitle=item["transport_node_name"],
                ) for item in local_ambiguities]
                return (station_results + local_results)[:limit]
            confidence = DiscoveryConfidence.EXACT if len(exact) == 1 else DiscoveryConfidence.AMBIGUOUS
            return [self._station_result(item[0], confidence, item[1]) for item in exact.values()][:limit]

        query_compact = compact_text(query)
        query_digits = "".join(re.findall(r"\d+", query_compact))
        scored: list[tuple[float, dict, str]] = []
        for station in self.stations:
            best_alias = max(station["aliases"], key=lambda alias: difflib.SequenceMatcher(None, query_compact, compact_text(alias)).ratio())
            if query_digits and query_digits not in compact_text(best_alias):
                continue
            score = difflib.SequenceMatcher(None, query_compact, compact_text(best_alias)).ratio()
            if score >= 0.84:
                scored.append((score, station, best_alias))
        scored.sort(key=lambda item: (-item[0], item[1]["canonical_name"]))
        if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.06):
            return [self._station_result(scored[0][1], DiscoveryConfidence.STRONG, scored[0][2])]
        if scored:
            return [self._station_result(item[1], DiscoveryConfidence.AMBIGUOUS, item[2]) for item in scored[:limit]]

        local = self.repository.search_hubs(query, limit)
        if local:
            top_exact = compact_text(local[0]["name"]) == query_compact
            confidence = DiscoveryConfidence.EXACT if top_exact else DiscoveryConfidence.LIKELY
            return [ResolvedLocation(
                internal_id=f"local-hub-{item['id']}", display_name=item["name"],
                coordinate=Coordinate(item["latitude"], item["longitude"]),
                entity_type=item["semantic_type"], source=DiscoverySource.LOCAL_CATALOG,
                confidence=confidence if len(local) == 1 or top_exact else DiscoveryConfidence.AMBIGUOUS,
                address=item["address"], subtitle=item["transport_node_name"],
            ) for item in local]

        try:
            matches = await self.provider.geocode(query, limit=limit)
        except ProviderError:
            matches = []
        return [ResolvedLocation(
            internal_id=f"onemap-{index}", display_name=match.label, coordinate=match.coordinate,
            entity_type=match.entity_type, source=DiscoverySource.ONEMAP,
            confidence=DiscoveryConfidence.LIKELY if len(matches) == 1 else DiscoveryConfidence.AMBIGUOUS,
            address=match.address,
        ) for index, match in enumerate(matches)]

    async def require_confident(self, query: str) -> ResolvedLocation:
        results = await self.resolve(query, 6)
        if not results:
            raise ProviderError(f"No confident Singapore location found for '{query}'")
        if results[0].confidence in {DiscoveryConfidence.AMBIGUOUS, DiscoveryConfidence.UNRESOLVED}:
            raise ProviderError(f"Location '{query}' is ambiguous; please select a suggestion")
        return results[0]


class _V073NeedResolver:
    def __init__(self, repository: HubRepository, live_provider: LivePlaceSearchProvider | None = None, concepts_path: Path | None = None, track_gaps: bool = False):
        self.repository = repository
        self.live_provider = live_provider
        payload = json.loads((concepts_path or DATA_DIR / "discovery-concepts.json").read_text(encoding="utf-8"))
        self.concepts = tuple(DiscoveryConcept(
            slug=item["slug"], display_name=item["display_name"], semantic_type=NeedSemanticType(item["semantic_type"]),
            aliases=tuple(item["aliases"]), category=item["category"], search_terms=tuple(item["search_terms"]),
            osm_tags=tuple(item.get("osm_tags", [])),
        ) for item in payload["concepts"])
        self.alias_index = {compact_text(alias): concept for concept in self.concepts for alias in concept.aliases}
        self.track_gaps = track_gaps
        self._counts: Counter[str] = Counter()
        self._sources: Counter[str] = Counter()
        self._gap_counts: Counter[str] = Counter()
        self._latencies: list[float] = []

    def metrics_snapshot(self) -> dict:
        ordered = sorted(self._latencies)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
        return {
            "total": self._counts["total"],
            "exact_local": self._counts["exact_local"],
            "semantic": self._counts["semantic"],
            "live_fallbacks": self._counts["live_fallbacks"],
            "unresolved": self._counts["unresolved"],
            "ambiguous": self._counts["ambiguous"],
            "discovery_calls": self._counts["discovery_calls"],
            "cache_hits": self._counts["cache_hits"],
            "average_latency_ms": round(sum(ordered) / len(ordered), 2) if ordered else 0.0,
            "p95_latency_ms": round(p95, 2),
            "source_distribution": dict(self._sources),
            "unresolved_concepts": dict(self._gap_counts.most_common(20)) if self.track_gaps else {},
            "gap_tracking_enabled": self.track_gaps,
        }

    def _concept(self, query: str) -> DiscoveryConcept | None:
        key = compact_text(query)
        if key in self.alias_index:
            return self.alias_index[key]
        matches = [(difflib.SequenceMatcher(None, key, alias).ratio(), concept) for alias, concept in self.alias_index.items()]
        score, concept = max(matches, default=(0.0, None), key=lambda item: item[0])
        return concept if score >= 0.9 else None

    @staticmethod
    def _dedupe(places: list[ResolvedPlace]) -> tuple[ResolvedPlace, ...]:
        kept: list[ResolvedPlace] = []
        for place in places:
            duplicate = next((item for item in kept if compact_text(item.display_name) == compact_text(place.display_name) and haversine_km(item.coordinate, place.coordinate) <= 0.12), None)
            if duplicate:
                index = kept.index(duplicate)
                kept[index] = ResolvedPlace(**{
                    **duplicate.__dict__,
                    "provenance": tuple(dict.fromkeys((*duplicate.provenance, place.source))),
                })
            else:
                kept.append(place)
        return tuple(kept)

    @staticmethod
    def _provider_category(places: tuple[ResolvedPlace, ...]) -> str | None:
        text = " ".join(
            " ".join((place.display_name, place.category or "", *place.evidence)).casefold()
            for place in places
        )
        mappings = (
            (("bubble tea", "milk tea", "tea shop"), "bubble_tea"),
            (("cafe", "coffee"), "coffee"),
            (("restaurant", "food"), "restaurants"),
            (("pharmacy", "chemist"), "pharmacy"),
            (("electronics", "mobile phone", "computer"), "electronics"),
            (("hair salon", "barber", "hairdresser"), "haircuts"),
            (("florist", "flower"), "florists"),
            (("pet shop", "pet store"), "pet_supplies"),
        )
        return next((category for terms, category in mappings if any(term in text for term in terms)), None)

    async def resolve(self, query: str, limit: int = 10, allow_live: bool = True) -> ResolvedNeed:
        started = time.perf_counter()
        concept = self._concept(query)
        local_query = concept.display_name if concept else query
        search_terms = concept.search_terms if concept else (query,)
        local_rows = self.repository.search_discovery(search_terms, concept.category if concept else None, limit)
        strong_terms = set(search_terms[:3])
        if concept and any(strong_terms & set(row["evidence"]) for row in local_rows):
            # Prefer direct name/tag/menu evidence over broad related-category
            # matches when at least one direct match exists.
            local_rows = tuple(row for row in local_rows if strong_terms & set(row["evidence"]))
        places = [ResolvedPlace(
            display_name=row["display_name"], canonical_name=row["display_name"],
            canonical_brand=row["canonical_brand"], coordinate=Coordinate(row["latitude"], row["longitude"]),
            address=row["address"], mall_or_hub=row["hub_name"], category=(row["categories"][0] if row["categories"] else None),
            concept=concept.slug if concept else None,
            source=DiscoverySource.OPENSTREETMAP if row["source"] == "openstreetmap" else DiscoverySource.LOCAL_CATALOG,
            confidence=DiscoveryConfidence.STRONG if strong_terms & set(row["evidence"]) else DiscoveryConfidence.LIKELY,
            evidence=tuple(row["evidence"]), source_id=None,
            provenance=(DiscoverySource.OPENSTREETMAP if row["source"] == "openstreetmap" else DiscoverySource.LOCAL_CATALOG,),
        ) for row in local_rows]
        catalog = self.repository.search_catalog(query, None, limit)
        exact_catalog = next((item for item in catalog if compact_text(item["display_name"]) == compact_text(query)), None)
        brand_match = self.repository.resolve_brand(query)
        semantic_type = concept.semantic_type if concept else (
            NeedSemanticType.BRAND if brand_match or (exact_catalog and exact_catalog["kind"] == "brand") else
            NeedSemanticType.SPECIFIC_BUSINESS if exact_catalog else NeedSemanticType.UNKNOWN
        )
        local_high = bool(brand_match or exact_catalog or any(place.confidence == DiscoveryConfidence.STRONG for place in places))
        conversational = len(query.split()) > 5 or bool(re.search(r"\b(i like|i love|tell me|what is|why)\b", query.casefold()))
        use_live = bool(allow_live and self.live_provider and not local_high and not conversational)
        failed = False
        before_calls = self.live_provider.calls if self.live_provider else 0
        before_hits = self.live_provider.cache_hits if self.live_provider else 0
        if use_live:
            try:
                places.extend(await self.live_provider.search(f"{local_query} Singapore", limit=limit))
            except LivePlaceSearchError:
                failed = True
        deduped = self._dedupe(places)
        if semantic_type == NeedSemanticType.UNKNOWN and deduped:
            semantic_type = NeedSemanticType.SPECIFIC_BUSINESS
        resolved_category = concept.category if concept else (
            brand_match["categories"][0] if brand_match and brand_match["categories"] else
            (exact_catalog["categories"][0] if exact_catalog and exact_catalog["categories"] else self._provider_category(deduped))
        )
        confidence = DiscoveryConfidence.EXACT if exact_catalog or brand_match else (
            DiscoveryConfidence.STRONG if concept and deduped else
            DiscoveryConfidence.LIKELY if deduped else DiscoveryConfidence.UNRESOLVED
        )
        clarification = None
        if confidence == DiscoveryConfidence.UNRESOLVED:
            clarification = f"I couldn't find a confident match for '{query}'."
        elif not concept and len(deduped) > 1 and not exact_catalog:
            confidence = DiscoveryConfidence.AMBIGUOUS
            clarification = "Choose the place you mean before optimizing."
        result = ResolvedNeed(
            original_query=query, semantic_type=semantic_type,
            canonical_concept=concept.display_name if concept else (brand_match["canonical_name"] if brand_match else (exact_catalog["display_name"] if exact_catalog else (deduped[0].display_name if deduped else None))),
            category=resolved_category,
            confidence=confidence, source=(deduped[0].source if deduped else None), related_terms=search_terms,
            places=deduped[:limit], live_fallback_used=use_live, live_provider_failed=failed,
            clarification=clarification,
            discovery_calls=(self.live_provider.calls - before_calls) if self.live_provider else 0,
            cache_hits=(self.live_provider.cache_hits - before_hits) if self.live_provider else 0,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        self._counts["total"] += 1
        self._counts["exact_local"] += int(bool(exact_catalog or brand_match))
        self._counts["semantic"] += int(concept is not None)
        self._counts["live_fallbacks"] += int(use_live)
        self._counts["unresolved"] += int(confidence == DiscoveryConfidence.UNRESOLVED)
        self._counts["ambiguous"] += int(confidence == DiscoveryConfidence.AMBIGUOUS)
        self._counts["discovery_calls"] += result.discovery_calls
        self._counts["cache_hits"] += result.cache_hits
        self._latencies.append(result.latency_ms)
        if result.source:
            self._sources[result.source.value] += 1
        if self.track_gaps and confidence == DiscoveryConfidence.UNRESOLVED:
            safe_term = normalize_text(query)[:80]
            if safe_term:
                self._gap_counts[safe_term] += 1
        return result


# The prior implementation remains private during the V0.7.4 migration so the
# new resolver can keep the stable public import without duplicating its API.
class NeedResolver:
    def __init__(
        self,
        repository: HubRepository,
        live_provider: LivePlaceSearchProvider | None = None,
        concepts_path: Path | None = None,
        track_gaps: bool = False,
        secondary_provider: LivePlaceSearchProvider | None = None,
        web_provider: WebDiscoveryProvider | None = None,
        semantic_provider: SemanticExpansionProvider | None = None,
        primary_calls_per_need: int = 2,
        secondary_calls_per_need: int = 1,
        web_calls_per_need: int = 1,
        grounding_candidate_limit: int = 4,
    ):
        self.repository = repository
        self.live_provider = live_provider
        self.secondary_provider = secondary_provider
        self.web_provider = web_provider
        self.semantic_provider = semantic_provider
        payload = json.loads((concepts_path or DATA_DIR / "discovery-concepts.json").read_text(encoding="utf-8"))
        self.concepts = tuple(DiscoveryConcept(
            slug=item["slug"], display_name=item["display_name"], semantic_type=NeedSemanticType(item["semantic_type"]),
            aliases=tuple(item["aliases"]), category=item["category"], search_terms=tuple(item["search_terms"]),
            osm_tags=tuple(item.get("osm_tags", [])),
        ) for item in payload["concepts"])
        self.alias_index = {compact_text(alias): concept for concept in self.concepts for alias in concept.aliases}
        self.open_parser = PlausibleNeedParser()
        self.track_gaps = track_gaps
        self.primary_calls_per_need = max(0, min(primary_calls_per_need, 2))
        self.secondary_calls_per_need = max(0, min(secondary_calls_per_need, 1))
        self.web_calls_per_need = max(0, min(web_calls_per_need, 2))
        self.grounding_candidate_limit = max(1, min(grounding_candidate_limit, 6))
        self._counts: Counter[str] = Counter()
        self._sources: Counter[str] = Counter()
        self._provider_calls: Counter[str] = Counter()
        self._gap_counts: Counter[str] = Counter()
        self._latencies: list[float] = []

    def parse_open_needs(self, text: str) -> tuple[OpenNeed, ...]:
        return self.open_parser.parse(text)

    def metrics_snapshot(self) -> dict:
        ordered = sorted(self._latencies)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
        total = self._counts["total"]
        return {
            "total": total,
            "plausible_need_acceptance": self._counts["plausible"],
            "false_nonsense_acceptance": self._counts["false_nonsense"],
            "exact_local": self._counts["exact_local"],
            "semantic": self._counts["semantic"],
            "llm_expansions": self._counts["llm_expansions"],
            "llm_latency_ms": round(self._counts["llm_latency_ms"], 2),
            "llm_input_tokens": self._counts["llm_input_tokens"],
            "llm_output_tokens": self._counts["llm_output_tokens"],
            "llm_reported_cost_usd": round(self._counts["llm_reported_cost_usd"], 6),
            "live_fallbacks": self._counts["live_fallbacks"],
            "secondary_live_fallbacks": self._counts["secondary_live_fallbacks"],
            "web_fallbacks": self._counts["web_fallbacks"],
            "grounding_successes": self._counts["grounding_successes"],
            "unresolved": self._counts["unresolved"],
            "zero_result_rate": self._counts["unresolved"] / total if total else 0,
            "ambiguous": self._counts["ambiguous"],
            "discovery_calls": self._counts["discovery_calls"],
            "cache_hits": self._counts["cache_hits"],
            "provider_calls": dict(self._provider_calls),
            "average_latency_ms": round(sum(ordered) / len(ordered), 2) if ordered else 0.0,
            "p95_latency_ms": round(p95, 2),
            "source_distribution": dict(self._sources),
            "unresolved_concepts": dict(self._gap_counts.most_common(20)) if self.track_gaps else {},
            "gap_tracking_enabled": self.track_gaps,
        }

    def _concept(self, query: str) -> DiscoveryConcept | None:
        key = compact_text(query)
        if key in self.alias_index:
            return self.alias_index[key]
        matches = [(difflib.SequenceMatcher(None, key, alias).ratio(), concept) for alias, concept in self.alias_index.items()]
        score, concept = max(matches, default=(0.0, None), key=lambda item: item[0])
        return concept if score >= 0.9 else None

    @staticmethod
    def _dedupe(places: list[ResolvedPlace]) -> tuple[ResolvedPlace, ...]:
        kept: list[ResolvedPlace] = []
        for place in places:
            duplicate = next((item for item in kept if (
                compact_text(item.display_name) == compact_text(place.display_name)
                or (item.address and place.address and compact_text(item.address) == compact_text(place.address))
            ) and haversine_km(item.coordinate, place.coordinate) <= 0.15), None)
            if duplicate:
                index = kept.index(duplicate)
                provenance = tuple(dict.fromkeys((*duplicate.provenance, *place.provenance, place.source)))
                tier_order = {EvidenceTier.WEAK: 0, EvidenceTier.SUPPORTED: 1, EvidenceTier.STRONG: 2, EvidenceTier.VERIFIED: 3}
                tier = max((duplicate.evidence_tier, place.evidence_tier), key=tier_order.get)
                kept[index] = dataclass_replace(
                    duplicate, provenance=provenance, evidence_tier=tier,
                    structured_evidence=(*duplicate.structured_evidence, *place.structured_evidence),
                    relevance_score=max(duplicate.relevance_score, place.relevance_score),
                )
            else:
                kept.append(place)
        return tuple(kept)

    async def _expansion(self, need: OpenNeed, concept: DiscoveryConcept | None) -> SemanticExpansion:
        if concept:
            return SemanticExpansion(
                semantic_type=concept.semantic_type, canonical_term=concept.display_name,
                generic_term=None, likely_place_types=(concept.category,),
                related_search_terms=concept.search_terms, category_hint=concept.category,
                confidence=DiscoveryConfidence.STRONG,
            )
        deterministic = deterministic_expansion(need)
        if need.inferred_type != NeedSemanticType.UNKNOWN or not self.semantic_provider:
            return deterministic
        try:
            expansion = await self.semantic_provider.expand(need)
            self._counts["llm_expansions"] += 1
            return expansion
        except (ValueError, httpx.HTTPError):
            return deterministic

    def _local_places(self, expansion: SemanticExpansion, concept: DiscoveryConcept | None, limit: int) -> list[ResolvedPlace]:
        terms = expansion.related_search_terms or (expansion.canonical_term,)
        rows = self.repository.search_discovery(terms, expansion.category_hint, limit)
        broad_terms = {compact_text(expansion.category_hint or ""), *(compact_text(term) for term in expansion.likely_place_types)}
        if expansion.semantic_type == NeedSemanticType.DISH and expansion.generic_term:
            broad_terms.add(compact_text(expansion.generic_term))
        direct_source = terms[:2] if expansion.semantic_type == NeedSemanticType.DISH else terms
        direct_terms = {
            normalize_text(term) for term in direct_source
            if len(compact_text(term)) >= 3 and compact_text(term) not in broad_terms
        }
        places: list[ResolvedPlace] = []
        for row in rows:
            evidence_text = " ".join((row["display_name"], *row["evidence"], *row["categories"]))
            direct = any(contains_normalized_phrase(evidence_text, term) for term in direct_terms)
            category_match = bool(expansion.category_hint and expansion.category_hint in row["categories"])
            if expansion.semantic_type == NeedSemanticType.DISH and not direct:
                continue
            if expansion.semantic_type in {NeedSemanticType.BRAND, NeedSemanticType.SPECIFIC_BUSINESS, NeedSemanticType.UNKNOWN} and not direct:
                continue
            tier = EvidenceTier.STRONG if direct else EvidenceTier.SUPPORTED
            source = DiscoverySource.OPENSTREETMAP if row["source"] == "openstreetmap" else DiscoverySource.LOCAL_CATALOG
            places.append(ResolvedPlace(
                display_name=row["display_name"], canonical_name=row["display_name"],
                canonical_brand=row["canonical_brand"], coordinate=Coordinate(row["latitude"], row["longitude"]),
                address=row["address"], mall_or_hub=row["hub_name"],
                category=row["categories"][0] if row["categories"] else expansion.category_hint,
                concept=concept.slug if concept else None, source=source,
                confidence=DiscoveryConfidence.STRONG if direct else DiscoveryConfidence.LIKELY,
                evidence=tuple(row["evidence"]), provenance=(source,), evidence_tier=tier,
                suitability="business_verified" if expansion.semantic_type == NeedSemanticType.DISH else "category_likely",
                relevance_score=1.0 if direct else 0.7,
                structured_evidence=(CandidatePlaceEvidence(
                    source=source, source_type="local_index", tier=tier, direct_name_match=direct,
                    category_match=category_match, item_or_dish_match=direct,
                    observed_text=tuple(row["evidence"]),
                ),),
            ))
        return places

    @staticmethod
    def _supported(place: ResolvedPlace, expansion: SemanticExpansion) -> ResolvedPlace | None:
        broad_terms = {compact_text(expansion.category_hint or ""), *(compact_text(term) for term in expansion.likely_place_types)}
        if expansion.semantic_type == NeedSemanticType.DISH and expansion.generic_term:
            broad_terms.add(compact_text(expansion.generic_term))
        direct_source = expansion.related_search_terms[:2] if expansion.semantic_type == NeedSemanticType.DISH else expansion.related_search_terms
        terms = tuple(
            normalize_text(term) for term in direct_source
            if len(compact_text(term)) >= 3 and compact_text(term) not in broad_terms
        )
        text = " ".join((place.display_name, place.category or "", *place.evidence))
        direct = any(contains_normalized_phrase(text, term) for term in terms)
        place_types = provider_category_terms(expansion)
        category_match = any(term and contains_normalized_phrase(text, term) for term in place_types)
        if expansion.semantic_type == NeedSemanticType.DISH and not direct:
            return None
        if expansion.semantic_type in {NeedSemanticType.BRAND, NeedSemanticType.SPECIFIC_BUSINESS, NeedSemanticType.UNKNOWN} and not direct:
            return None
        if expansion.semantic_type in {NeedSemanticType.PRODUCT, NeedSemanticType.SERVICE} and not (direct or category_match):
            return None
        tier = EvidenceTier.STRONG if direct else EvidenceTier.SUPPORTED
        suitability = "business_verified" if direct and expansion.semantic_type == NeedSemanticType.DISH else "category_likely"
        return dataclass_replace(
            place, confidence=DiscoveryConfidence.STRONG if direct else DiscoveryConfidence.LIKELY,
            evidence_tier=tier, suitability=suitability, relevance_score=1.0 if direct else 0.65,
            structured_evidence=(*place.structured_evidence, CandidatePlaceEvidence(
                source=place.source, source_type="normalized_provider", tier=tier,
                direct_name_match=direct, category_match=category_match,
                item_or_dish_match=direct, observed_text=(place.display_name, place.category or ""),
            )),
        )

    async def _provider_search(
        self, provider: LivePlaceSearchProvider, expansion: SemanticExpansion,
        context: DiscoverySearchContext | None, limit: int, call_budget: int,
    ) -> tuple[list[ResolvedPlace], bool]:
        found: list[ResolvedPlace] = []
        queries = tuple(dict.fromkeys((expansion.canonical_term, *expansion.related_search_terms)))[:call_budget]
        for term in queries:
            try:
                raw = await provider.search(term, limit=limit, context=context, category_hint=expansion.category_hint)
            except LivePlaceSearchError:
                return found, True
            found.extend(place for item in raw if (place := self._supported(item, expansion)) is not None)
            if found:
                break
        return found, False

    async def _ground_web(
        self, candidates: list[WebCandidate], expansion: SemanticExpansion,
        context: DiscoverySearchContext | None, limit: int,
    ) -> list[ResolvedPlace]:
        providers = tuple(item for item in (self.live_provider, self.secondary_provider) if item)
        grounded: list[ResolvedPlace] = []
        grounding_context = (
            dataclass_replace(context, route_geometry=()) if context and context.route_geometry else context
        )
        for candidate in candidates[: self.grounding_candidate_limit]:
            observed = f"{candidate.title} {candidate.snippet}"
            direct_business_evidence = contains_normalized_phrase(
                observed, expansion.canonical_term,
            )
            if (
                expansion.semantic_type == NeedSemanticType.SPECIFIC_BUSINESS
                and direct_business_evidence
            ):
                business = expansion.canonical_term
            else:
                segments = [
                    item.strip() for item in re.split(r"\s+[|–—]\s+", candidate.title)
                    if 1 <= len(item.split()) <= 7
                ]
                business = min(
                    segments or [candidate.title.strip()],
                    key=lambda item: (
                        contains_normalized_phrase(item, expansion.canonical_term),
                        len(item.split()),
                    ),
                )
            if (
                len(business) < 3
                or normalize_text(business) in {
                    "singapore", "singapore shop", "singapore store", "official site",
                    "online store", "where to buy", "best in singapore",
                }
            ):
                continue
            local_expansion = SemanticExpansion(
                semantic_type=NeedSemanticType.SPECIFIC_BUSINESS, canonical_term=business,
                generic_term=None, likely_place_types=expansion.likely_place_types,
                related_search_terms=(business,), category_hint=expansion.category_hint,
                confidence=DiscoveryConfidence.LIKELY,
            )
            local = self._local_places(local_expansion, None, limit)
            matches = local
            if not matches:
                for provider in providers:
                    matches, _ = await self._provider_search(
                        provider, local_expansion, grounding_context, limit, 1,
                    )
                    if matches:
                        break
            # A geocoded mall is not independent evidence of a shop there.
            # Keep only named business matches; never rename a mall as an outlet.
            location_hints = web_location_hints(observed)
            for place in matches[:2]:
                if location_hints and not any(
                    contains_normalized_phrase(f"{place.address or ''} {place.mall_or_hub or ''}", hint)
                    for hint in location_hints
                ):
                    continue
                grounded.append(dataclass_replace(
                    place, source=DiscoverySource.WEB_GROUNDED,
                    provenance=tuple(dict.fromkeys((*place.provenance, DiscoverySource.TAVILY))),
                    structured_evidence=(*place.structured_evidence, CandidatePlaceEvidence(
                        source=DiscoverySource.TAVILY, source_type="web_result", tier=EvidenceTier.SUPPORTED,
                        direct_name_match=True, observed_text=(candidate.title, candidate.snippet[:160]),
                    )),
                ))
        return grounded

    async def resolve(
        self,
        query: str,
        limit: int = 10,
        allow_live: bool = True,
        context: DiscoverySearchContext | None = None,
        open_need: OpenNeed | None = None,
    ) -> ResolvedNeed:
        started = time.perf_counter()
        parsed = open_need or next(iter(self.parse_open_needs(query)), None)
        if parsed is None:
            self._counts["total"] += 1
            latency = round((time.perf_counter() - started) * 1000, 2)
            self._latencies.append(latency)
            return ResolvedNeed(
                original_query=query, semantic_type=NeedSemanticType.UNKNOWN,
                canonical_concept=None, category=None, confidence=DiscoveryConfidence.UNRESOLVED,
                source=None, related_terms=(), places=(),
                clarification=f"'{query}' does not look like an everyday errand.", latency_ms=latency,
            )
        self._counts["plausible"] += 1
        concept = self._concept(parsed.normalized_text)
        expansion = await self._expansion(parsed, concept)
        if expansion.method == "llm":
            self._counts["llm_latency_ms"] += expansion.latency_ms
            self._counts["llm_input_tokens"] += expansion.input_tokens or 0
            self._counts["llm_output_tokens"] += expansion.output_tokens or 0
            self._counts["llm_reported_cost_usd"] += expansion.cost_usd or 0
        parsed = parsed.model_copy(update={
            "inferred_type": expansion.semantic_type,
            "known_concept_id": concept.slug if concept else None,
            "category_hint": expansion.category_hint,
            "related_search_terms": expansion.related_search_terms,
            "likely_place_types": expansion.likely_place_types,
            "resolution_status": NeedResolutionStatus.EXPANDED,
        })
        # Rank a bounded local pool before cutting to the response limit.
        places = self._local_places(expansion, concept, min(max(limit, limit * 8), 80))
        local_count = len(places)
        provider_calls: Counter[str] = Counter()
        failed = False
        web_used = False
        grounding_calls = 0
        cache_before = sum(item.cache_hits for item in (self.live_provider, self.secondary_provider) if item)
        call_before = {item.name: item.calls for item in (self.live_provider, self.secondary_provider) if item}
        latency_before = {item.name: item.latency_ms for item in (self.live_provider, self.secondary_provider) if item}
        web_latency_before = self.web_provider.latency_ms if self.web_provider else 0.0
        has_context_relevant_place = any(context_relevant(place, context) for place in places)
        if allow_live and not has_context_relevant_place and self.live_provider and self.primary_calls_per_need:
            found, provider_failed = await self._provider_search(self.live_provider, expansion, context, limit, self.primary_calls_per_need)
            places.extend(found)
            failed = failed or provider_failed
            has_context_relevant_place = any(context_relevant(place, context) for place in places)
        if allow_live and not has_context_relevant_place and self.secondary_provider and self.secondary_calls_per_need:
            found, provider_failed = await self._provider_search(self.secondary_provider, expansion, context, limit, self.secondary_calls_per_need)
            places.extend(found)
            failed = failed or provider_failed
            self._counts["secondary_live_fallbacks"] += 1
            has_context_relevant_place = any(context_relevant(place, context) for place in places)
        if allow_live and not has_context_relevant_place and self.web_provider and self.web_calls_per_need:
            web_used = True
            self._counts["web_fallbacks"] += 1
            try:
                web_before = self.web_provider.calls
                web_candidates = await self.web_provider.search(expansion.canonical_term, self.grounding_candidate_limit)
                provider_calls[self.web_provider.name] += self.web_provider.calls - web_before
                grounding_calls = min(len(web_candidates), self.grounding_candidate_limit)
                places.extend(await self._ground_web(web_candidates, expansion, context, limit))
                self._counts["grounding_successes"] += int(bool(places))
            except WebDiscoveryError:
                failed = True
        for provider in (self.live_provider, self.secondary_provider):
            if provider:
                provider_calls[provider.name] += provider.calls - call_before[provider.name]
        provider_latency_ms = {
            provider.name: round(max(0.0, provider.latency_ms - latency_before[provider.name]), 2)
            for provider in (self.live_provider, self.secondary_provider) if provider
            and provider.calls - call_before[provider.name] > 0
        }
        if self.web_provider and provider_calls[self.web_provider.name] > 0:
            provider_latency_ms[self.web_provider.name] = round(
                max(0.0, self.web_provider.latency_ms - web_latency_before), 2,
            )
        deduped = tuple(sorted(
            self._dedupe(places),
            key=lambda item: (
                not context_relevant(item, context), -item.relevance_score,
                distance_to_geometry_km(item.coordinate, context.route_geometry) if context and context.route_geometry else 0,
                item.display_name,
            ),
        ))[:limit]
        status = NeedResolutionStatus.RESOLVED if deduped else NeedResolutionStatus.UNRESOLVED
        parsed = parsed.model_copy(update={"resolution_status": status})
        confidence = DiscoveryConfidence.STRONG if any(item.evidence_tier in {EvidenceTier.VERIFIED, EvidenceTier.STRONG} for item in deduped) else (
            DiscoveryConfidence.LIKELY if deduped else DiscoveryConfidence.UNRESOLVED
        )
        warnings: list[str] = []
        if expansion.semantic_type == NeedSemanticType.PRODUCT and deduped:
            warnings.append("These businesses are relevant to the product category; current item-level stock is not guaranteed.")
        if expansion.semantic_type == NeedSemanticType.DISH and deduped and not any(item.evidence_tier == EvidenceTier.STRONG for item in deduped):
            warnings.append("Menu details could not be independently verified.")
        clarification = None if deduped else f"We couldn't find a reliable place for '{query}'."
        latency = round((time.perf_counter() - started) * 1000, 2)
        cache_hits = sum(item.cache_hits for item in (self.live_provider, self.secondary_provider) if item) - cache_before
        result = ResolvedNeed(
            original_query=query, semantic_type=expansion.semantic_type,
            canonical_concept=expansion.canonical_term, category=expansion.category_hint,
            confidence=confidence, source=deduped[0].source if deduped else None,
            related_terms=expansion.related_search_terms, places=deduped,
            live_fallback_used=bool(sum(provider_calls.values())), live_provider_failed=failed,
            clarification=clarification, discovery_calls=sum(provider_calls.values()), cache_hits=cache_hits,
            latency_ms=latency, open_need=parsed, provider_calls=dict(provider_calls),
            provider_latency_ms=provider_latency_ms,
            web_fallback_used=web_used, grounding_calls=grounding_calls, warnings=tuple(warnings),
        )
        self._counts["total"] += 1
        self._counts["exact_local"] += int(bool(local_count))
        self._counts["semantic"] += int(concept is not None or expansion.semantic_type != NeedSemanticType.UNKNOWN)
        self._counts["live_fallbacks"] += int(any(name != "tavily" for name in provider_calls))
        self._counts["unresolved"] += int(not deduped)
        self._counts["ambiguous"] += int(confidence == DiscoveryConfidence.AMBIGUOUS)
        self._counts["discovery_calls"] += result.discovery_calls
        self._counts["cache_hits"] += result.cache_hits
        self._provider_calls.update(provider_calls)
        self._latencies.append(latency)
        if result.source:
            self._sources[result.source.value] += 1
        if self.track_gaps and not deduped:
            safe_term = normalize_text(query)[:80]
            if safe_term:
                self._gap_counts[safe_term] += 1
        logger.info(
            "need_discovery type=%s places=%s local_places=%s provider_calls=%s "
            "provider_latency_ms=%s cache_hits=%s total_latency_ms=%s unresolved=%s",
            expansion.semantic_type.value, len(deduped), local_count, dict(provider_calls),
            provider_latency_ms, cache_hits, latency, not bool(deduped),
        )
        return result
