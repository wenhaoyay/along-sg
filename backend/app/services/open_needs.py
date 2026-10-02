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
    r"how\s+are|make\s+me\s+laugh|joke|weather|news)\b"
    # A greeting or a test is not an errand, however short: "hello" was being
    # sent to discovery and came back as an errand called "hello".
    r"|^(?:hi|hello|hey|hiya|yo|ok|okay|thanks|thank\s+you|test|testing|asdf\w*|lol|nothing|idk)$",
    re.IGNORECASE,
)
# Words that open a clause without being the thing wanted ("some groceries",
# "also a coffee", "quickly grab panadol"). Stripped repeatedly together with
# INTENT_PREFIX, so "need to grab some panadol" reaches "panadol".
FILLER_PREFIX = re.compile(
    r"^(?:also|then|maybe|quickly|just|and|to|some|a\s+few|a\s+bit\s+of|a|an|the|my|me|"
    r"go(?:\s+to)?|stop\s+(?:by|at)|drop\s+by|on\s+the\s+way)\s+",
    re.IGNORECASE,
)
FILLER_SUFFIX = re.compile(
    r"\s+(?:please|too|as\s+well|also|on\s+the\s+way|along\s+the\s+way)$", re.IGNORECASE
)
# A clause that says HOW to travel, not WHAT to get. The intent parser reads
# these as preferences; counted as needs, "prefer Guardian" was sent to
# discovery as if it were an errand. Matched against normalized text.
PREFERENCE_CLAUSE = re.compile(
    r"^(?:(?:i\s+)?(?:prefer(?:ably)?|ideally|rather)\b"
    r"|(?:i\s+)?(?:dont|don\s+t|do\s+not)\s+(?:want|like|mind)\s+(?:to\s+)?walk"
    r"|(?:not\s+too\s+much|not\s+much|minimal|less|little|no\s+long|as\s+little)\s+walk"
    r"|(?:minimi[sz]e|avoid|fewer|less|no(?:\s+extra)?)\s+(?:walking|transfers?|changes?)"
    r"|(?:i\s*m\s+)?in\s+a\s+(?:rush|hurry)$|urgent$|asap$|quick(?:ly)?$"
    r"|(?:under|within|less\s+than|no\s+more\s+than|max(?:imum)?)\s+\d+\s*(?:min|mins|minutes?)\b"
    r"|any\s+brand|brand\s+doesn?\s*t\s+matter|if\s+(?:convenient|possible)$"
    r"|(?:in\s+)?(?:one|the\s+same)\s+(?:stop|mall|place)$|together$)",
    re.IGNORECASE,
)


def clean_clause(part: str) -> str:
    """The thing wanted, without the words around it."""
    previous = None
    value = part.strip(" -")
    while value != previous:
        previous = value
        value = INTENT_PREFIX.sub("", value)
        value = FILLER_PREFIX.sub("", value)
        value = FILLER_SUFFIX.sub("", value).strip(" -")
    return value


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
        parts = re.split(
            r"\s*(?:,|;|&|\+|\band\b|\bplus\b|\bthen\b|\bbut\b)\s*", cleaned, flags=re.IGNORECASE
        )
        cleaned_parts = (clean_clause(part) for part in parts if part.strip())
        return [
            part for part in cleaned_parts
            if part and not PREFERENCE_CLAUSE.search(normalize_text(part))
        ]

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
