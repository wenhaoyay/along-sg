from __future__ import annotations

import re

from app.discovery_models import (
    DiscoveryConfidence,
    NeedResolutionStatus,
    NeedSemanticType,
    OpenNeed,
    SemanticExpansion,
)
from app.poi_taxonomy import normalize_text


INTENT_PREFIX = re.compile(
    r"^(?:please\s+)?(?:i\s+)?(?:want|need|buy|get|find|pick\s*up|eat|drink|looking\s+for|"
    r"grab|dabao|collect|search\s+for|where\s+can\s+i\s+get|where\s+to\s+buy)\s+(?:to\s+|some\s+|a\s+|an\s+|the\s+)?",
    re.IGNORECASE,
)
NON_ERRAND = re.compile(
    r"\b(?:i\s+(?:like|love|hate|think)|tell\s+me|what\s+is|who\s+is|why\s+is|"
    r"how\s+are|make\s+me\s+laugh|joke|weather|news)\b",
    re.IGNORECASE,
)


def open_category(raw_text: str, index: int = 0) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalize_text(raw_text)).strip("_")[:48] or "need"
    return f"open_{slug}_{index + 1}" if index else f"open_{slug}"


class PlausibleNeedParser:
    """Conservative lexical parser: validity is independent of taxonomy coverage."""

    _food_terms = {
        "mee pok", "meepok", "fishball noodles", "hor fun", "chicken rice", "cai fan",
        "caifan", "ban mian", "laksa", "prata", "mala", "ramen", "sushi", "dim sum",
        "matcha", "durian", "kaya toast", "bak chor mee", "nasi lemak", "roti john",
    }
    _service_terms = {
        "passport photo": ("printing", "photo_shop"),
        "haircut": ("haircuts", "hair_salon"),
        "key duplication": ("repairs", "locksmith"),
        "printing": ("printing", "copy_shop"),
        "spectacles repair": ("optical", "optician"),
        "parcel drop off": ("parcel", "parcel_service"),
        "parcel drop-off": ("parcel", "parcel_service"),
        "atm": ("banking", "atm"),
    }
    _product_terms = {
        "panadol": ("pharmacy", "paracetamol pain relief"),
        "paracetamol": ("pharmacy", "pain relief medicine"),
        "usb c cable": ("electronics", "phone accessories"),
        "usb-c cable": ("electronics", "phone accessories"),
        "phone charger": ("electronics", "phone accessories"),
        "printer ink": ("stationery", "printer supplies"),
        "cat litter": ("pet_supplies", "pet supplies"),
        "cat food": ("pet_supplies", "pet supplies"),
        "mosquito repellent": ("pharmacy", "personal care"),
        "toothpaste": ("pharmacy", "personal care"),
        "contact lens solution": ("optical", "contact lens care"),
        "bubble wrap": ("hardware", "packing supplies"),
        "shoe glue": ("hardware", "adhesive"),
        "flowers": ("florists", "florist"),
        "birthday cake": ("bakeries", "cake shop"),
        "birthday candles": ("household", "party supplies"),
        "umbrella": ("convenience", "general merchandise"),
    }

    def parse(self, text: str) -> tuple[OpenNeed, ...]:
        normalized = normalize_text(text)
        if not normalized or NON_ERRAND.search(normalized):
            return ()
        parts = self._split(text)
        needs = tuple(self._need(part) for part in parts if self._plausible(part))
        return needs[:2]

    @staticmethod
    def _split(text: str) -> list[str]:
        cleaned = re.sub(r"[.!?]+$", "", text.strip())
        parts = re.split(r"\s*(?:,|&|\+|\band\b|\bplus\b)\s*", cleaned, flags=re.IGNORECASE)
        return [INTENT_PREFIX.sub("", part).strip(" -") for part in parts if part.strip()]

    @staticmethod
    def _plausible(part: str) -> bool:
        normalized = normalize_text(part)
        if not normalized or NON_ERRAND.search(normalized):
            return False
        words = normalized.split()
        return 1 <= len(words) <= 12 and any(character.isalpha() for character in normalized)

    def _need(self, raw: str) -> OpenNeed:
        normalized = normalize_text(raw)
        lookup = normalized.replace("-", " ")
        optional = bool(re.search(r"\b(?:if convenient|optional|if possible)\b", normalized))
        hard_brand = bool(re.search(r"\b(?:must be|only|specifically)\b", normalized))
        normalized = re.sub(r"\b(?:if convenient|optional|if possible)\b", "", normalized).strip()
        if lookup in self._service_terms:
            category, place_type = self._service_terms[lookup]
            semantic = NeedSemanticType.SERVICE
            hints = {"service_hint": normalized}
            related = (normalized, place_type)
        elif lookup in self._product_terms:
            category, generic = self._product_terms[lookup]
            semantic = NeedSemanticType.PRODUCT
            hints = {"product_hint": normalized}
            related = (normalized, generic, category.replace("_", " "))
            place_type = category
        elif (
            raw.strip() == raw.strip().title()
            or re.fullmatch(r"[A-Z][A-Za-z'’&.-]*(?:\s+[A-Z][A-Za-z'’&.-]*){0,3}", raw.strip())
        ) and len(raw.split()) <= 4 and lookup not in self._food_terms:
            category, place_type = None, "place"
            semantic = NeedSemanticType.SPECIFIC_BUSINESS
            hints = {"brand_hint": raw.strip()}
            related = (normalized,)
        elif lookup in self._food_terms or re.search(r"\b(?:noodle|noodles|rice|cake|tea|coffee|ramen|sushi|prata|mala|nugget|nuggets)\b", lookup):
            category, place_type = "restaurants", "restaurant"
            semantic = NeedSemanticType.DISH
            hints = {"dish_hint": normalized}
            related = (normalized, "food")
        elif re.search(r"\b(?:repair|replacement|photo|printing|haircut|duplication|drop off|drop-off)\b", lookup):
            category, place_type = "repairs", "service"
            semantic = NeedSemanticType.SERVICE
            hints = {"service_hint": normalized}
            related = (normalized, "service")
        elif re.search(r"\b(?:cable|charger|ink|litter|repellent|glue|wrap|solution|candles?|food|meds?|medicine|batter(?:y|ies)|adapter|protector|bulbs?|tape|treats|detergent|cream|spray|bags?|boxes?|paper|pens?)\b", lookup):
            category, place_type = None, "shop"
            semantic = NeedSemanticType.PRODUCT
            hints = {"product_hint": normalized}
            related = (normalized,)
        else:
            category, place_type = None, "place"
            semantic = NeedSemanticType.UNKNOWN
            hints = {}
            related = (normalized,)
        return OpenNeed(
            raw_text=raw.strip(), normalized_text=normalized, inferred_type=semantic,
            category_hint=category, hard_brand=hard_brand, optional=optional,
            substitution_allowed=not hard_brand, confidence=DiscoveryConfidence.LIKELY,
            resolution_status=NeedResolutionStatus.OPEN, related_search_terms=tuple(dict.fromkeys(related)),
            likely_place_types=(place_type,), evidence_requirements=self._requirements(semantic), **hints,
        )

    @staticmethod
    def _requirements(semantic: NeedSemanticType) -> tuple[str, ...]:
        if semantic == NeedSemanticType.DISH:
            return ("direct dish/name/menu evidence", "grounded Singapore coordinates")
        if semantic == NeedSemanticType.PRODUCT:
            return ("relevant business category", "grounded Singapore coordinates", "no stock guarantee")
        return ("relevant name/category evidence", "grounded Singapore coordinates")


def deterministic_expansion(need: OpenNeed) -> SemanticExpansion:
    terms = tuple(dict.fromkeys((*need.related_search_terms, need.normalized_text)))
    return SemanticExpansion(
        semantic_type=need.inferred_type,
        canonical_term=need.raw_text.strip(),
        generic_term=terms[1] if len(terms) > 1 else None,
        likely_place_types=need.likely_place_types,
        related_search_terms=terms,
        category_hint=need.category_hint,
        confidence=need.confidence,
    )
