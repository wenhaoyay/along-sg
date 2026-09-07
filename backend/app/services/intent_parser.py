from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.db import HubRepository
from app.intent_models import (
    IntentErrand,
    IntentMetricsSnapshot,
    IntentParseDiagnostics,
    IntentParseResponse,
    IntentPreferences,
    IntentStatus,
    IntentV1,
    ParseMethod,
    TransferTolerance,
    Urgency,
    WalkingTolerance,
)
from app.poi_taxonomy import CATEGORY_ALIASES, normalize_text
from app.providers.llm import IntentLLMProvider


logger = logging.getLogger("intent_parser")

CATEGORY_PHRASES = {
    **CATEGORY_ALIASES,
    "dinner": "fast_food",
    "cheap dinner": "fast_food",
    "food": "fast_food",
    "something fried": "fried_chicken",
    "fried": "fried_chicken",
    "fried food": "fried_chicken",
    "sweet drink": "bubble_tea",
    "boba": "bubble_tea",
    "tea drink": "bubble_tea",
    "toothpaste": "pharmacy",
    "medication": "pharmacy",
    "withdraw cash": "banking",
    "cash": "banking",
    "cash machine": "banking",
    "snacks": "convenience",
    "charger": "electronics",
    "phone cable": "electronics",
    "pick up parcel": "parcel",
    "collect parcel": "parcel",
}

CATEGORY_PRIORITY = (
    "fried_chicken", "bubble_tea", "coffee", "groceries", "pharmacy",
    "convenience", "banking", "electronics", "parcel", "fast_food",
    "japanese_food", "korean_food", "burgers", "bakeries", "dessert",
    "restaurants", "stationery", "hardware", "florists", "pet_supplies",
    "clothing", "household", "printing", "haircuts", "optical", "repairs",
)


@dataclass
class _Entity:
    category: str
    phrase: str
    brand: str | None = None
    position: int = 0


class IntentMetrics:
    def __init__(self) -> None:
        self.total_parses = 0
        self.deterministic_parses = 0
        self.llm_parses = 0
        self.validation_failures = 0
        self.unresolved_terms = 0
        self.fallbacks = 0
        self.clarifications = 0
        self.corrections = 0
        self.near_miss_alternatives_selected = 0
        self.parser_latency_ms_total = 0.0
        self.llm_latency_ms_total = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.measured_cost_usd: float | None = None

    def snapshot(self) -> IntentMetricsSnapshot:
        total = self.total_parses
        return IntentMetricsSnapshot(
            total_parses=total,
            deterministic_parses=self.deterministic_parses,
            llm_parses=self.llm_parses,
            deterministic_parse_rate=self.deterministic_parses / total if total else 0,
            llm_parse_rate=self.llm_parses / total if total else 0,
            validation_failures=self.validation_failures,
            unresolved_terms=self.unresolved_terms,
            fallbacks=self.fallbacks,
            fallback_rate=self.fallbacks / total if total else 0,
            clarifications=self.clarifications,
            clarification_rate=self.clarifications / total if total else 0,
            corrections=self.corrections,
            near_miss_alternatives_selected=self.near_miss_alternatives_selected,
            parser_latency_ms_total=round(self.parser_latency_ms_total, 2),
            llm_latency_ms_total=round(self.llm_latency_ms_total, 2),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            measured_cost_usd=self.measured_cost_usd,
        )


class DeterministicIntentParser:
    def __init__(self, repository: HubRepository):
        self.repository = repository

    def parse(self, text: str) -> IntentParseResponse:
        started = time.perf_counter()
        normalized = normalize_text(text)
        diagnostics = IntentParseDiagnostics()
        if not normalized:
            return self._unresolved(text, ["empty request"], started, diagnostics)

        # These compositional concepts are intentionally delegated: matching only
        # the easy clause would silently drop part of the user's request.
        if any(term in normalized for term in ("caffeinated", "stock the pantry")):
            return self._unresolved(text, [text.strip()], started, diagnostics)

        conflict = self._detect_conflict(normalized)
        if conflict:
            return self._clarification(text, conflict, started, diagnostics)

        entities = self._entities(normalized)
        unknown_brand = self._unknown_explicit_brand(normalized, entities)
        if unknown_brand:
            diagnostics.unresolved_brands.append(unknown_brand)
            return self._unresolved(text, [unknown_brand], started, diagnostics)
        if not entities:
            return self._unresolved(text, [text.strip()], started, diagnostics)
        if len(entities) > 2:
            return self._clarification(
                text, "I found more than two errands. Which two should I optimise?",
                started, diagnostics,
            )

        required: list[IntentErrand] = []
        optional: list[IntentErrand] = []
        for entity in entities:
            is_optional = self._is_optional(normalized, entity, len(entities))
            exact_brand, preferred_brand, substitutes = self._brand_semantics(
                normalized, entity
            )
            errand = IntentErrand(
                category=entity.category,
                required=not is_optional,
                exact_brand=exact_brand,
                preferred_brand=preferred_brand,
                substitutes_allowed=substitutes,
            )
            (optional if is_optional else required).append(errand)

        preferences = self._preferences(text, normalized)
        try:
            intent = IntentV1(
                original_text=text,
                required_errands=required,
                optional_errands=optional,
                preferences=preferences,
                parse_method=ParseMethod.DETERMINISTIC,
                confidence=0.98,
            )
        except ValidationError:
            diagnostics.validation_failures += 1
            return self._clarification(
                text, "I could not represent that combination safely. Please confirm the two errands.",
                started, diagnostics,
            )
        diagnostics.parser_latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return IntentParseResponse(
            status=IntentStatus.RESOLVED,
            intent=intent,
            diagnostics=diagnostics,
        )

    def _entities(self, normalized: str) -> list[_Entity]:
        entities: list[_Entity] = []
        for brand in self.repository.brand_catalog():
            aliases = {
                normalize_text(brand["canonical_name"]),
                normalize_text(brand["slug"]),
                *(normalize_text(alias) for alias in brand["aliases"]),
            }
            matches = [
                (normalized.find(alias), alias) for alias in aliases
                if alias and re.search(rf"\b{re.escape(alias)}\b", normalized)
            ]
            if not matches:
                continue
            position, phrase = min(matches, key=lambda item: item[0])
            category = next(
                (item for item in CATEGORY_PRIORITY if item in brand["categories"]),
                brand["categories"][0] if brand["categories"] else "",
            )
            if category:
                entities.append(_Entity(category, phrase, brand["canonical_name"], position))

        for phrase, category in sorted(CATEGORY_PHRASES.items(), key=lambda item: -len(item[0])):
            normalized_phrase = normalize_text(phrase)
            match = re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized)
            if not match:
                continue
            existing = next((entity for entity in entities if entity.category == category), None)
            if existing:
                if match.start() < existing.position:
                    existing.position = match.start()
                continue
            # Avoid generic "food" duplicating a more specific food category.
            if category == "fast_food" and any(
                entity.category == "fried_chicken" for entity in entities
            ):
                continue
            entities.append(_Entity(category, normalized_phrase, None, match.start()))
        return sorted(entities, key=lambda entity: entity.position)

    @staticmethod
    def _detect_conflict(normalized: str) -> str | None:
        if (
            any(term in normalized for term in ("must be", "specifically", "dont substitute", "only "))
            and any(term in normalized for term in ("any brand", "other fried chicken", "substitute is fine"))
        ):
            return "You asked for both a specific brand and an alternative. Which one should I treat as required?"
        if "minimal walking" in normalized and any(term in normalized for term in ("dont mind walking", "don t mind walking")):
            return "Should I minimise walking, or is extra walking acceptable?"
        return None

    @staticmethod
    def _unknown_explicit_brand(normalized: str, entities: list[_Entity]) -> str | None:
        patterns = (
            r"must be ([a-z0-9 ]+?)(?: specifically| and| plus| but|$)",
            r"need ([a-z0-9 ]+?) specifically(?: and| plus| but|$)",
            r"prefer ([a-z0-9 ]+?)(?: but| and| plus|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                value = match.group(1).strip()
                recognized = any(
                    value in {
                        entity.phrase,
                        normalize_text(entity.brand or ""),
                    }
                    for entity in entities
                )
                if value and value not in CATEGORY_PHRASES and not recognized:
                    return value
        return None

    @staticmethod
    def _is_optional(normalized: str, entity: _Entity, entity_count: int) -> bool:
        phrase = re.escape(entity.phrase)
        if re.search(rf"\b{phrase}\b(?: is)? if convenient", normalized):
            return True
        if re.search(rf"skip (?:the )?\b{phrase}\b", normalized):
            return True
        if re.search(rf"\b{phrase}\b.{0,25}\boptional\b", normalized):
            return True
        if entity_count == 1 and "only if it adds" in normalized:
            return True
        return False

    @staticmethod
    def _brand_semantics(normalized: str, entity: _Entity) -> tuple[str | None, str | None, bool]:
        if not entity.brand:
            return None, None, True
        phrase = re.escape(entity.phrase)
        preferred = bool(
            re.search(rf"(?:prefer|ideally)\s+{phrase}\b", normalized)
            or re.search(rf"\b{phrase}\b\s+preferably", normalized)
            or "any " + entity.category.replace("_", " ") in normalized
            or any(term in normalized for term in ("dont really care what brand", "don t really care what brand"))
            or "other fried chicken is okay" in normalized
        )
        if preferred:
            return None, entity.brand, True
        return entity.brand, None, False

    @staticmethod
    def _preferences(original: str, normalized: str) -> IntentPreferences:
        max_detour = None
        max_detour_is_hard = False
        detour_match = re.search(
            r"(?:less than|under|no more than|max(?:imum)?|within|more than)\s*(\d+(?:\.\d+)?)\s*(?:min|minute)",
            normalized,
        )
        if detour_match:
            max_detour = float(detour_match.group(1))
            window = normalized[max(0, detour_match.start() - 18):detour_match.end() + 8]
            max_detour_is_hard = bool(
                re.search(r"\b(max(?:imum)?|must|strict|no more than)\b", window)
                or re.search(r"\bunder\s+\d+(?:\.\d+)?\s*(?:min|minute)s?\s+max\b", window)
            ) and not any(term in window for term in ("try", "prefer", "ideally"))
        walking = WalkingTolerance.STANDARD
        if any(term in normalized for term in ("minimal walking", "minimise walking", "minimize walking", "less walking", "as little walking")):
            walking = WalkingTolerance.MINIMAL
        elif any(term in normalized for term in ("dont mind walking", "don t mind walking")):
            walking = WalkingTolerance.HIGH
        max_walking = None
        max_walking_is_hard = False
        walking_match = re.search(r"(?:walk|walking).{0,12}(\d+(?:\.\d+)?)\s*(?:min|minute)", normalized)
        if walking_match:
            max_walking = float(walking_match.group(1))
            walking_window = normalized[max(0, walking_match.start() - 18):walking_match.end() + 8]
            max_walking_is_hard = bool(
                re.search(r"\b(max(?:imum)?|must|strict|no more than)\b", walking_window)
            ) and not any(term in walking_window for term in ("try", "prefer", "ideally"))
        transfer = TransferTolerance.STANDARD
        max_transfers = None
        max_transfers_is_hard = False
        if any(term in normalized for term in ("no extra transfer", "dont give me another train transfer", "don t give me another train transfer", "no more transfers")):
            transfer = TransferTolerance.NO_EXTRA
            max_transfers = 0
            max_transfers_is_hard = True
        elif any(term in normalized for term in ("fewer transfers", "avoid transfers", "less transferring")):
            transfer = TransferTolerance.PREFER_FEWER
        urgency = Urgency.NORMAL
        if any(term in normalized for term in ("in a rush", "urgent", "im in a rush", "quickly")):
            urgency = Urgency.URGENT
        elif "soon" in normalized:
            urgency = Urgency.SOON
        arrival_by = None
        arrival_match = re.search(r"arrive by (\d{4}-\d{2}-\d{2})[ t](\d{1,2}:\d{2})", original, re.I)
        if arrival_match:
            arrival_by = datetime.fromisoformat(f"{arrival_match.group(1)}T{arrival_match.group(2)}")
        return IntentPreferences(
            max_detour_minutes=max_detour,
            walking_tolerance=walking,
            max_extra_walking_minutes=max_walking,
            transfer_tolerance=transfer,
            max_additional_transfers=max_transfers,
            max_detour_is_hard=max_detour_is_hard,
            max_extra_walking_is_hard=max_walking_is_hard,
            max_additional_transfers_is_hard=max_transfers_is_hard,
            prefer_consolidated_stops=any(
                term in normalized for term in ("one stop", "same mall", "together", "consolidated")
            ),
            urgency=urgency,
            arrival_by=arrival_by,
        )

    @staticmethod
    def _unresolved(text, terms, started, diagnostics) -> IntentParseResponse:
        diagnostics.parser_latency_ms = round((time.perf_counter() - started) * 1000, 2)
        diagnostics.clarification_required = True
        return IntentParseResponse(
            status=IntentStatus.UNRESOLVED,
            unresolved_terms=terms,
            clarification_question=(
                "I couldn't find an errand in that request. Try ‘KFC and bubble tea’, "
                "‘buy toothpaste with minimal walking’, or ‘coffee if convenient’."
            ),
            diagnostics=diagnostics,
        )

    @staticmethod
    def _clarification(text, question, started, diagnostics) -> IntentParseResponse:
        diagnostics.parser_latency_ms = round((time.perf_counter() - started) * 1000, 2)
        diagnostics.clarification_required = True
        return IntentParseResponse(
            status=IntentStatus.NEEDS_CLARIFICATION,
            clarification_question=question,
            diagnostics=diagnostics,
        )


class IntentParserService:
    def __init__(
        self,
        repository: HubRepository,
        llm_provider: IntentLLMProvider | None = None,
        metrics: IntentMetrics | None = None,
    ):
        self.repository = repository
        self.deterministic = DeterministicIntentParser(repository)
        self.llm_provider = llm_provider
        self.metrics = metrics or IntentMetrics()

    async def parse(self, text: str, correction: bool = False) -> IntentParseResponse:
        started = time.perf_counter()
        result = self.deterministic.parse(text)
        if result.status == IntentStatus.RESOLVED:
            self._record(result, ParseMethod.DETERMINISTIC, correction)
            return result
        if result.status == IntentStatus.NEEDS_CLARIFICATION or self.llm_provider is None:
            result.diagnostics.fallback_used = self.llm_provider is None
            self._record(result, None, correction)
            return result

        try:
            llm = await self.llm_provider.parse_intent(
                text, self.repository.category_catalog(), self.repository.brand_catalog()
            )
            canonical, unresolved = self._canonicalize(llm.intent)
            diagnostics = IntentParseDiagnostics(
                parser_latency_ms=round((time.perf_counter() - started) * 1000, 2),
                llm_latency_ms=round(llm.latency_ms, 2),
                input_tokens=llm.input_tokens,
                output_tokens=llm.output_tokens,
                total_tokens=llm.total_tokens,
                estimated_cost_usd=llm.cost_usd,
                fallback_used=True,
                clarification_required=bool(unresolved),
                correction_applied=correction,
            )
            if unresolved:
                diagnostics.unresolved_brands.extend(unresolved)
                response = IntentParseResponse(
                    status=IntentStatus.UNRESOLVED,
                    unresolved_terms=unresolved,
                    clarification_question="I still cannot resolve: " + ", ".join(unresolved),
                    diagnostics=diagnostics,
                )
                self._record(response, None, correction)
                return response
            response = IntentParseResponse(
                status=IntentStatus.RESOLVED,
                intent=canonical,
                diagnostics=diagnostics,
            )
            self._record(response, ParseMethod.LLM, correction)
            return response
        except (ValidationError, ValueError, httpx.HTTPError) as error:
            logger.warning("intent_llm_fallback_failed type=%s", type(error).__name__)
            result.diagnostics.fallback_used = True
            result.diagnostics.validation_failures += 1
            self._record(result, None, correction)
            return result

    def validate_intent(self, intent: IntentV1) -> tuple[IntentV1 | None, list[str]]:
        """Resolve user- or model-supplied terms against the canonical local catalog."""
        canonical, unresolved = self._canonicalize(intent)
        if canonical is not None:
            canonical = canonical.model_copy(update={"parse_method": intent.parse_method})
        return canonical, unresolved

    def _canonicalize(self, intent: IntentV1) -> tuple[IntentV1 | None, list[str]]:
        valid_categories = set(self.repository.category_catalog())
        unresolved: list[str] = []
        required: list[IntentErrand] = []
        optional: list[IntentErrand] = []
        for source, target in (
            (intent.required_errands, required), (intent.optional_errands, optional)
        ):
            for item in source:
                category = CATEGORY_ALIASES.get(normalize_text(item.category), normalize_text(item.category).replace(" ", "_"))
                if category not in valid_categories and not (category.startswith("open_") and item.open_need):
                    unresolved.append(item.category)
                    continue
                exact = self.repository.resolve_brand(item.exact_brand) if item.exact_brand else None
                preferred = self.repository.resolve_brand(item.preferred_brand) if item.preferred_brand else None
                place = self.repository.resolve_place(item.exact_place, category) if item.exact_place else None
                if item.exact_brand and not exact:
                    unresolved.append(item.exact_brand)
                    continue
                if item.preferred_brand and not preferred:
                    unresolved.append(item.preferred_brand)
                    continue
                if item.exact_place and not place:
                    unresolved.append(item.exact_place)
                    continue
                brand = exact or preferred
                if brand and category not in brand["categories"]:
                    unresolved.append(f"{brand['canonical_name']} as {category}")
                    continue
                target.append(IntentErrand(
                    category=category,
                    required=item.required,
                    exact_brand=exact["canonical_name"] if exact else None,
                    preferred_brand=preferred["canonical_name"] if preferred else None,
                    exact_place=place["display_name"] if place else None,
                    substitutes_allowed=item.substitutes_allowed,
                    discovery_concept=item.discovery_concept,
                    open_need=item.open_need,
                    discovery_category=item.discovery_category,
                ))
        if unresolved:
            return None, unresolved
        return intent.model_copy(update={
            "required_errands": required,
            "optional_errands": optional,
            "parse_method": ParseMethod.LLM,
        }), []

    def _record(
        self,
        result: IntentParseResponse,
        method: ParseMethod | None,
        correction: bool,
    ) -> None:
        self.metrics.total_parses += 1
        self.metrics.parser_latency_ms_total += result.diagnostics.parser_latency_ms
        self.metrics.llm_latency_ms_total += result.diagnostics.llm_latency_ms
        self.metrics.validation_failures += result.diagnostics.validation_failures
        self.metrics.unresolved_terms += len(result.unresolved_terms)
        self.metrics.fallbacks += int(result.diagnostics.fallback_used)
        self.metrics.clarifications += int(result.status != IntentStatus.RESOLVED)
        self.metrics.corrections += int(correction)
        self.metrics.input_tokens += result.diagnostics.input_tokens or 0
        self.metrics.output_tokens += result.diagnostics.output_tokens or 0
        if method == ParseMethod.DETERMINISTIC:
            self.metrics.deterministic_parses += 1
        elif method == ParseMethod.LLM:
            self.metrics.llm_parses += 1
