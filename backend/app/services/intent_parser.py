from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
    SpellingCorrection,
    TransferTolerance,
    Urgency,
    WalkingTolerance,
)
from app.poi_taxonomy import CATEGORY_ALIASES, normalize_text
from app.providers.llm import IntentLLMProvider
from app.services.open_needs import PlausibleNeedParser


logger = logging.getLogger("intent_parser")

SINGAPORE = ZoneInfo("Asia/Singapore")
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# ATMs and post offices have categories of their own (an ATM is a two-minute
# stop, not a fifteen-minute bank visit). Every such phrase also records the
# concept it came from.
ATM_CATEGORY = "atm"
POST_OFFICE_CATEGORY = "post_office"

CATEGORY_PHRASES = {
    **CATEGORY_ALIASES,
    # Dinner is a meal, not a burger: fast food only when it is asked for.
    "dinner": "restaurants",
    "lunch": "restaurants",
    "supper": "restaurants",
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
    "withdraw cash": ATM_CATEGORY,
    "cash": ATM_CATEGORY,
    "cash machine": ATM_CATEGORY,
    "atm": ATM_CATEGORY,
    "snacks": "convenience",
    "charger": "electronics",
    "phone cable": "electronics",
    "pick up parcel": "parcel",
    "collect parcel": "parcel",
    "post a parcel": "parcel",
    "post parcel": "parcel",
    "send a parcel": "parcel",
    "post office": POST_OFFICE_CATEGORY,
    "panadol": "pharmacy",
    "paracetamol": "pharmacy",
    "medicine": "pharmacy",
    "plasters": "pharmacy",
    "vitamins": "pharmacy",
    "sunscreen": "pharmacy",
    "milk": "groceries",
    "eggs": "groceries",
    "bread": "groceries",
    "fruits": "groceries",
    "vegetables": "groceries",
    "birthday cake": "bakeries",
    "cake": "bakeries",
    "ice cream": "dessert",
    "gelato": "dessert",
    "cat food": "pet_supplies",
    "dog food": "pet_supplies",
    "pet food": "pet_supplies",
    "passport photo": "printing",
    "photocopy": "printing",
    # Singlish. Kopi and teh are what a kopitiam or cafe sells; "makan" is
    # eating out in general, so the broad restaurants category.
    "kopi": "coffee",
    "kopi o": "coffee",
    "kopi c": "coffee",
    "kopi peng": "coffee",
    "teh": "coffee",
    "teh o": "coffee",
    "teh c": "coffee",
    "teh peng": "coffee",
    "teh tarik": "coffee",
    "kopitiam": "coffee",
    "makan": "restaurants",
}

# The narrower thing a phrase names, kept on the errand when the category
# planned for it is broader.
REQUESTED_CONCEPTS = {
    "post office": "post_office",
    "atm": "atm",
    "cash machine": "atm",
    "withdraw cash": "atm",
    "cash": "atm",
}

# Words in other scripts, and emoji, read as the English the rest of the
# parser understands. Longest first at match time, so 药房 is not 药 + 房.
TRANSLATIONS = {
    "珍珠奶茶": "bubble tea",
    "奶茶": "bubble tea",
    "咖啡": "coffee",
    "牛奶": "milk",
    "药房": "pharmacy",
    "药店": "pharmacy",
    "药": "medicine",
    "取钱": "withdraw cash",
    "提款机": "atm",
    "提款": "withdraw cash",
    "超市": "supermarket",
    "面包": "bread",
    "鸡蛋": "eggs",
    "快递": "parcel",
    "包裹": "parcel",
    "买": "buy",
    "和": "and",
    "跟": "and",
    "还有": "and",
    "然后": "then",
    "或者": "or",
    "或": "or",
    "🧋": "bubble tea",
    "☕": "coffee",
    "💊": "medicine",
    "🍔": "burger",
    "🍗": "fried chicken",
    "🛒": "groceries",
    "🏧": "atm",
    "📦": "parcel",
    "🍦": "ice cream",
    "🍨": "ice cream",
    "🎂": "cake",
    "💐": "flowers",
}
# Chinese words that carry no errand ("I want", "please", "a cup of").
TRANSLATION_FILLERS = (
    "我想要", "我要", "我想", "想要", "帮我", "请", "一下", "一杯", "一些", "一点",
    "去", "的", "了", "吧", "要",
)
_TRANSLATION_PATTERN = re.compile(
    "|".join(
        re.escape(term)
        for term in sorted([*TRANSLATIONS, *TRANSLATION_FILLERS], key=len, reverse=True)
    )
)
_PUNCTUATION_TRANSLATIONS = str.maketrans({
    "，": ",", "、": ",", "。": ".", "；": ";", "！": "!", "？": "?", "：": ":",
    "’": "'", "‘": "'", "“": '"', "”": '"', "️": "", "‍": "",
})

# How, not what. Never an errand by itself.
TAKEAWAY = re.compile(r"\b(?:tapau|ta\s+pau|da\s*bao|da\s*pao|take[\s-]?away)\b", re.IGNORECASE)
# Words that soften or stress a request without naming anything. "strictly"
# is kept as meaning: it makes the stated limits hard.
STRICT = re.compile(r"\bstrict(?:ly)?\b", re.IGNORECASE)
FILLER = re.compile(r"\b(?:please|pls|plz|lah|la|leh|lor|ah|hor|meh)\b", re.IGNORECASE)
MAYBE = re.compile(r"\bmaybe\b", re.IGNORECASE)

FOOD_CATEGORIES = frozenset({
    "fast_food", "fried_chicken", "burgers", "bubble_tea", "coffee", "restaurants",
    "japanese_food", "korean_food", "chinese_food", "bakeries", "dessert",
})

# Phrases that bring a clock time in. A bare hour ("by 6") is left alone: it
# could be either side of noon.
_ARRIVAL_LEAD = (
    r"(?:\b(?:i\s+)?(?:need|have|want|got)\s+to\s+)?"
    r"(?:\b(?:arrive|reach|be\s+there|get\s+there|be\s+home|get\s+home|reach\s+home|be\s+back)\s+)?"
)
ISO_ARRIVAL = re.compile(_ARRIVAL_LEAD + r"\b(?:arrive\s+)?by\s+(\d{4}-\d{2}-\d{2})[ tT](\d{1,2}:\d{2})", re.IGNORECASE)
CLOCK_ARRIVAL = re.compile(
    _ARRIVAL_LEAD
    + r"\b(?:by|before|latest\s+by|no\s+later\s+than)\s+"
    r"(?:(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m\b\.?|(\d{1,2})[:.](\d{2})(?:\s*(?:h|hrs)\b)?)",
    re.IGNORECASE,
)

# Words around a brand that rule it out. "if not X" offers X as a fallback,
# so it is not a negation.
NEGATION = (
    r"(?<!\bif\s)\b(?:not|no|except|excluding|without|anything\s+but|anywhere\s+but|"
    r"avoid(?:ing)?|other\s+than|never|instead\s+of|rather\s+than|"
    r"(?:i\s+)?(?:dont|don'?t|do\s+not)\s+want)\s+(?:the\s+|any\s+)?"
)
CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|&|\+|\band\b|\bplus\b|\bthen\b|\bbut\b|\bor\b)\s*", re.IGNORECASE)

# Never corrected by spelling: everyday words near a catalog word ("break" is
# one letter from "bread", "changer" from "charger").
STOP_WORDS = frozenset({
    "about", "after", "again", "also", "anything", "anywhere", "arrive", "avoid", "before",
    "brand", "break", "bring", "buy", "came", "check", "cheap", "close", "collect", "come",
    "could", "changer", "dont", "drop", "else", "evening", "extra", "fries", "from", "going",
    "grab", "great", "have", "hello", "help", "here", "home", "hurry", "ideally", "into",
    "joke", "just", "least", "less", "like", "love", "make", "mall", "maybe", "minimal",
    "minute", "minutes", "more", "morning", "much", "near", "nearby", "nearest", "need",
    "night", "nothing", "other", "pick", "place", "please", "pointing", "possible",
    "prefer", "quick", "quickly", "really", "rush", "same", "shop", "should", "some",
    "something", "soon", "station", "stop", "store", "strict", "strictly", "take", "tell",
    "test", "testing", "than", "thanks", "that", "then", "there", "thing", "think",
    "today", "together", "tomorrow", "tonight", "train", "trains", "transfer",
    "transfers", "under", "urgent", "walk", "walking", "want", "weather", "what", "where",
    "while", "with", "within", "without", "work", "would",
})

# A brand's errand is the first of its categories here. Burgers sit ahead of
# coffee because McDonald's also lists coffee (McCafe) and was read as a
# coffee errand.
CATEGORY_PRIORITY = (
    "fried_chicken", "burgers", "bubble_tea", "coffee", "groceries", "pharmacy",
    "convenience", "atm", "banking", "electronics", "post_office", "parcel", "fast_food",
    "japanese_food", "korean_food", "bakeries", "dessert",
    "restaurants", "stationery", "hardware", "florists", "pet_supplies",
    "clothing", "household", "printing", "haircuts", "optical", "repairs",
)


@dataclass
class _Entity:
    category: str
    phrase: str
    brand: str | None = None
    position: int = 0
    brand_options: list[str] = field(default_factory=list)


@dataclass
class PreparedRequest:
    """A request with everything that is not an errand taken out.

    `text` is what the errand parser and open discovery read. What was taken
    out is kept as meaning (a time, an excluded brand, "takeaway", "strictly")
    or reported back (`not_understood`), never silently dropped.
    """

    original: str
    text: str
    arrival_by: datetime | None = None
    excluded_brands: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)
    strict: bool = False
    not_understood: list[str] = field(default_factory=list)
    corrections: list[tuple[str, str]] = field(default_factory=list)

    @property
    def discovery_text(self) -> str:
        """The clauses open discovery splits: no lone hedges left as needs."""
        return _tidy(MAYBE.sub(" ", self.text))


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    text = re.sub(r"([,;])(?:\s*[,;])+", r"\1", text)
    return text.strip(" ,.;:-")


def _alias_pattern(alias: str) -> str:
    # "mcdonald s" matches McDonald's, McDonalds and McDonald’s; ASCII-only
    # boundaries so the é in "KOI Thé" does not stop a match on "koi th".
    words = [re.escape(word) for word in alias.split()]
    return r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(words) + r"(?![a-z0-9])"


def _edit_distance(left: str, right: str, limit: int) -> int:
    """Optimal string alignment distance (a swap counts once), capped."""
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous_previous: list[int] = []
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i] + [0] * len(right)
        for j, right_char in enumerate(right, 1):
            cost = 0 if left_char == right_char else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if (
                i > 1 and j > 1 and left_char == right[j - 2] and left[i - 2] == right_char
            ):
                current[j] = min(current[j], previous_previous[j - 2] + 1)
        if min(current) > limit:
            return limit + 1
        previous_previous, previous = previous, current
    return previous[-1]


# Faces, hearts and thumbs say how, not what: not worth a "didn't understand".
_MOOD_SYMBOLS = frozenset("❤♥☺👍👌🙏✨🔥💯")


def _foreign(fragment: str) -> bool:
    """Whether a run of non-ASCII text carries words or symbols (not just
    punctuation or an accented Latin letter, as in "KOI Thé")."""
    for character in fragment:
        if character in _MOOD_SYMBOLS or 0x1F600 <= ord(character) <= 0x1F64F:
            continue
        kind = unicodedata.category(character)
        if kind[0] in {"L", "N"} and "LATIN" not in unicodedata.name(character, ""):
            return True
        if kind == "So":
            return True
    return False


@lru_cache(maxsize=1)
def _discovery_words() -> frozenset[str]:
    """Words open discovery already knows ("batteries", "laksa"). They are
    real requests, so spelling correction must never turn them into a
    catalog word ("batteries" is two edits from "bakeries")."""
    phrases: list[str] = [
        *PlausibleNeedParser._food_terms,
        *PlausibleNeedParser._product_terms,
        *PlausibleNeedParser._service_terms,
    ]
    try:
        payload = json.loads((DATA_DIR / "discovery-concepts.json").read_text(encoding="utf-8"))
        for concept in payload.get("concepts", []):
            phrases.extend(concept.get("aliases", []))
            phrases.extend(concept.get("search_terms", []))
    except (OSError, ValueError):
        pass
    return frozenset(word for phrase in phrases for word in normalize_text(phrase).split())


def _clock_label(value: datetime, now: datetime) -> str:
    day = "today" if value.date() == now.date() else "tomorrow"
    return f"{value.strftime('%H:%M')} {day}"


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
    def __init__(
        self,
        repository: HubRepository,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(SINGAPORE))

    # ----------------------------------------------------------- preparation

    def prepare(self, text: str, brands: tuple[dict[str, Any], ...] | None = None) -> PreparedRequest:
        """Translate, then lift out times, excluded brands, modifiers and filler."""
        brands = self.repository.brand_catalog() if brands is None else brands
        prepared = PreparedRequest(original=text, text=text)
        value = text.translate(_PUNCTUATION_TRANSLATIONS)
        value = _TRANSLATION_PATTERN.sub(lambda match: f" {TRANSLATIONS.get(match.group(0), '')} ", value)

        # Whatever is still in another script cannot be represented: say so.
        def unknown(match: re.Match[str]) -> str:
            if _foreign(match.group(0)):
                prepared.not_understood.append(match.group(0).strip())
                return " "
            return match.group(0)

        value = re.sub(r"[^\x00-\x7f]+", unknown, value)

        prepared.arrival_by, value = self._arrival(value)

        aliases: dict[str, str] = {}
        for brand in brands:
            for alias in (brand["canonical_name"], brand["slug"], *brand["aliases"]):
                normalized = normalize_text(alias)
                if normalized:
                    aliases.setdefault(normalized, brand["canonical_name"])
        if aliases:
            brand_pattern = "(?:" + "|".join(
                _alias_pattern(alias) for alias in sorted(aliases, key=len, reverse=True)
            ) + ")"
            negated = re.compile(
                NEGATION + "(" + brand_pattern + r"(?:\s*(?:,|/|\bor\b|\bnor\b)\s*" + brand_pattern + ")*)",
                re.IGNORECASE,
            )

            def exclude(match: re.Match[str]) -> str:
                for found in re.finditer(brand_pattern, match.group(1), re.IGNORECASE):
                    canonical = aliases.get(normalize_text(found.group(0)))
                    if canonical and canonical not in prepared.excluded_brands:
                        prepared.excluded_brands.append(canonical)
                return " , "

            value = negated.sub(exclude, value)

        if TAKEAWAY.search(value):
            prepared.modifiers.append("takeaway")
            value = TAKEAWAY.sub(" ", value)
        if STRICT.search(value):
            prepared.strict = True
            value = STRICT.sub(" ", value)
        value = FILLER.sub(" ", value)
        value = self._correct_spelling(_tidy(value), brands, prepared)
        prepared.text = _tidy(value)
        return prepared

    def _arrival(self, value: str) -> tuple[datetime | None, str]:
        iso = ISO_ARRIVAL.search(value)
        if iso:
            arrival = datetime.fromisoformat(f"{iso.group(1)}T{iso.group(2).zfill(5)}")
            return arrival.replace(tzinfo=SINGAPORE), value[:iso.start()] + " , " + value[iso.end():]
        for match in CLOCK_ARRIVAL.finditer(value):
            hour_12, minute_12, half, hour_24, minute_24 = match.groups()
            if hour_12 is not None:
                hours, minute = [int(hour_12)], int(minute_12 or 0)
                if not 1 <= hours[0] <= 12:
                    continue
                hours = [hours[0] % 12 + (12 if half.lower() == "p" else 0)]
            else:
                hours, minute = [int(hour_24)], int(minute_24)
                if hours[0] > 23:
                    continue
                if len(hour_24) == 1 and 1 <= hours[0] <= 9:
                    # "by 6:30" without am/pm: whichever 6:30 comes next.
                    hours.append(hours[0] + 12)
            if minute > 59:
                continue
            now = self.clock().astimezone(SINGAPORE)
            candidates = []
            for hour in hours:
                arrival = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if arrival <= now:
                    arrival += timedelta(days=1)
                candidates.append(arrival)
            return min(candidates), value[:match.start()] + " , " + value[match.end():]
        return None, value

    def _correct_spelling(
        self, value: str, brands: tuple[dict[str, Any], ...], prepared: PreparedRequest,
    ) -> str:
        """Read a near-miss spelling of a catalog word as that word.

        Only in a clause nothing else was found in, only for words of four
        letters or more against catalog words of five or more, starting with
        the same letter, within one edit (two from seven letters), and only
        when exactly one catalog word is that close.
        """
        known_words: set[str] = set()
        for phrase in CATEGORY_PHRASES:
            known_words.update(normalize_text(phrase).split())
        for brand in brands:
            for alias in (brand["canonical_name"], brand["slug"], *brand["aliases"]):
                known_words.update(normalize_text(alias).split())
        targets = sorted(word for word in known_words if len(word) >= 5 and word.isalpha())
        known_words |= _discovery_words()
        corrections: dict[str, str] = {}
        for clause in CLAUSE_SPLIT.split(value):
            normalized = normalize_text(clause)
            if not normalized or self._entities(normalized, brands):
                continue
            for token in normalized.split():
                if (
                    len(token) < 4 or not token.isalpha() or token in STOP_WORDS
                    or token in known_words or token in corrections
                ):
                    continue
                limit = 1 if len(token) <= 6 else 2
                scored = [
                    (distance, word) for word in targets
                    if word[0] == token[0]
                    and (distance := _edit_distance(token, word, limit)) <= limit
                ]
                if not scored:
                    continue
                best = min(distance for distance, _ in scored)
                winners = [word for distance, word in scored if distance == best]
                if len(winners) == 1:
                    corrections[token] = winners[0]
        for typed, understood in corrections.items():
            value = re.sub(
                rf"(?<![a-z0-9]){re.escape(typed)}(?![a-z0-9])", understood, value, flags=re.IGNORECASE,
            )
            prepared.corrections.append((typed, understood))
        return value

    def discovery_text(self, text: str) -> str:
        return self.prepare(text).discovery_text

    def names_errand(self, text: str) -> bool:
        """Whether a phrase is just an errand ("the post office", "Guardian").

        "go to the pharmacy" reads like a new destination to the journey
        reference extractor; it is an errand when all it names is one.
        """
        brands = self.repository.brand_catalog()
        normalized = normalize_text(self.prepare(text, brands).text)
        normalized = re.sub(r"^(?:the|a|an|some|any|nearest|nearby|closest)\s+", "", normalized)
        if not normalized:
            return False
        phrases = {normalize_text(phrase) for phrase in CATEGORY_PHRASES}
        for brand in brands:
            phrases.update(
                normalize_text(alias)
                for alias in (brand["canonical_name"], brand["slug"], *brand["aliases"])
            )
        return normalized in phrases

    def preferences_for(self, text: str) -> IntentPreferences:
        return self._preferences(normalize_text(text), self.prepare(text))

    # ---------------------------------------------------------------- parsing

    def parse(self, text: str) -> IntentParseResponse:
        started = time.perf_counter()
        diagnostics = IntentParseDiagnostics()
        if not normalize_text(text) and not text.strip():
            return self._unresolved(text, ["empty request"], started, diagnostics)
        brands = self.repository.brand_catalog()
        prepared = self.prepare(text, brands)
        normalized = normalize_text(prepared.text)
        corrections = [
            SpellingCorrection(typed=typed, understood_as=understood)
            for typed, understood in prepared.corrections
        ]

        # These compositional concepts are intentionally delegated: matching only
        # the easy clause would silently drop part of the user's request.
        if any(term in normalized for term in ("caffeinated", "stock the pantry")):
            return self._unresolved(text, [text.strip()], started, diagnostics)

        conflict = self._detect_conflict(normalized)
        if conflict:
            return self._clarification(text, conflict, started, diagnostics)

        entities = self._entities(normalized, brands) if normalized else []
        unknown_brand = self._unknown_explicit_brand(prepared.text, entities)
        if unknown_brand:
            diagnostics.unresolved_brands.append(unknown_brand)
            return self._unresolved(text, [unknown_brand], started, diagnostics)
        notes: list[str] = []
        confidence = 0.98
        inferred = False
        if not entities and prepared.excluded_brands:
            # "not McDonald's" on its own: the same kind of place, anywhere else.
            entity = self._entity_for_excluded(prepared.excluded_brands[0], brands)
            if entity:
                entities = [entity]
                confidence = 0.8
                inferred = True
                notes.append(
                    f"Read as {entity.category.replace('_', ' ')} anywhere except "
                    f"{prepared.excluded_brands[0]}."
                )
        if not entities:
            if prepared.arrival_by is not None and not normalized:
                return self._clarification(
                    text,
                    f"I have the time (arrive by {_clock_label(prepared.arrival_by, self.clock())}). "
                    "What errand should I plan?",
                    started, diagnostics,
                )
            terms = prepared.not_understood or [text.strip() or "empty request"]
            return self._unresolved(text, terms, started, diagnostics)
        entities = self._merge_brand_options(normalized, entities, notes)
        if len(entities) > 2:
            return self._clarification(
                text, "I found more than two errands. Which two should I optimise?",
                started, diagnostics,
            )

        takeaway = "takeaway" in prepared.modifiers
        if takeaway and not any(entity.category in FOOD_CATEGORIES for entity in entities):
            notes.append("Takeaway only applies to food or drink, so it was left out.")
        required: list[IntentErrand] = []
        optional: list[IntentErrand] = []
        for entity in entities:
            is_optional = self._is_optional(normalized, entity, len(entities))
            exact_brand, preferred_brand, substitutes = self._brand_semantics(
                normalized, entity
            )
            excluded = self._exclusions_for(entity, entities, prepared.excluded_brands, brands)
            concept = REQUESTED_CONCEPTS.get(entity.phrase)
            errand = IntentErrand(
                category=entity.category,
                required=not is_optional,
                exact_brand=exact_brand,
                preferred_brand=preferred_brand,
                substitutes_allowed=substitutes,
                excluded_brands=excluded,
                brand_options=entity.brand_options,
                modifiers=["takeaway"] if takeaway and entity.category in FOOD_CATEGORIES else [],
                requested_concept=concept,
            )
            if concept == "post_office" and POST_OFFICE_CATEGORY != "post_office":
                notes.append("Post offices are planned as parcel points for now.")
            (optional if is_optional else required).append(errand)
        if prepared.excluded_brands and not inferred:
            notes.append("Excluding " + " and ".join(prepared.excluded_brands) + ".")
        if prepared.arrival_by is not None:
            notes.append(f"Arrive by {_clock_label(prepared.arrival_by, self.clock())}.")
        if corrections:
            confidence = min(confidence, 0.75)
            notes.append(
                "Did you mean "
                + ", ".join(f"‘{item.understood_as}’ for ‘{item.typed}’" for item in corrections)
                + "?"
            )

        preferences = self._preferences(normalize_text(text), prepared)
        try:
            intent = IntentV1(
                original_text=text,
                required_errands=required,
                optional_errands=optional,
                preferences=preferences,
                parse_method=ParseMethod.DETERMINISTIC,
                confidence=confidence,
            )
        except ValidationError:
            diagnostics.validation_failures += 1
            return self._clarification(
                text, "I could not represent that combination safely. Please confirm the two errands.",
                started, diagnostics,
            )
        diagnostics.parser_latency_ms = round((time.perf_counter() - started) * 1000, 2)
        question = None
        if prepared.not_understood:
            question = (
                "I didn't understand "
                + ", ".join(f"‘{term}’" for term in prepared.not_understood)
                + ", so it is not in the plan. You can continue with the rest or edit the request."
            )
        return IntentParseResponse(
            status=IntentStatus.RESOLVED,
            intent=intent,
            unresolved_terms=list(prepared.not_understood),
            clarification_question=question,
            diagnostics=diagnostics,
            spelling_corrections=corrections,
            notes=notes,
        )

    def understands(self, text: str) -> bool:
        """Whether a single clause names a known category or brand."""
        return bool(self._entities(normalize_text(text)))

    def _entities(
        self, normalized: str, brands: tuple[dict[str, Any], ...] | None = None,
    ) -> list[_Entity]:
        entities: list[_Entity] = []
        for brand in self.repository.brand_catalog() if brands is None else brands:
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
            category = self._brand_category(brand)
            if category:
                entities.append(_Entity(category, phrase, brand["canonical_name"], position))

        claimed: list[tuple[int, int]] = []
        for phrase, category in sorted(CATEGORY_PHRASES.items(), key=lambda item: -len(item[0])):
            normalized_phrase = normalize_text(phrase)
            match = re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized)
            if not match:
                continue
            # Inside a longer phrase already matched ("food" in "cat food") the
            # shorter one is not a second errand. Phrases go longest first.
            if any(start <= match.start() and match.end() <= end for start, end in claimed):
                continue
            claimed.append((match.start(), match.end()))
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
    def _brand_category(brand: dict[str, Any]) -> str:
        return next(
            (item for item in CATEGORY_PRIORITY if item in brand["categories"]),
            brand["categories"][0] if brand["categories"] else "",
        )

    def _entity_for_excluded(
        self, excluded: str, brands: tuple[dict[str, Any], ...],
    ) -> _Entity | None:
        brand = next((item for item in brands if item["canonical_name"] == excluded), None)
        category = self._brand_category(brand) if brand else ""
        return _Entity(category, category.replace("_", " ")) if category else None

    @staticmethod
    def _exclusions_for(
        entity: _Entity,
        entities: list[_Entity],
        excluded: list[str],
        brands: tuple[dict[str, Any], ...],
    ) -> list[str]:
        """An excluded brand belongs to the errands it could have served
        ("Guardian, not Watsons" -> the pharmacy errand). One that serves none
        of them ("no KFC, any burger") is ruled out for every errand."""
        categories = {item["canonical_name"]: set(item["categories"]) for item in brands}
        result: list[str] = []
        for brand in excluded:
            served = categories.get(brand, set())
            could_serve = entity.category in served or not any(
                item.category in served for item in entities
            )
            if could_serve and brand != entity.brand:
                result.append(brand)
        return result

    @staticmethod
    def _merge_brand_options(
        normalized: str, entities: list[_Entity], notes: list[str],
    ) -> list[_Entity]:
        """"Starbucks or Toast Box" ("KFC, if not Popeyes") is one errand."""
        merged: list[_Entity] = []
        for entity in entities:
            previous = next(
                (
                    item for item in merged
                    if item.category == entity.category and item.brand and entity.brand
                    and re.search(r"\b(?:or|if not|otherwise|else)\b", normalized[item.position:entity.position])
                ),
                None,
            )
            if previous is None:
                merged.append(entity)
                continue
            if not previous.brand_options:
                previous.brand_options = [previous.brand]
            previous.brand_options.append(entity.brand)
            previous.brand = None
        for entity in merged:
            if entity.brand_options:
                notes.append(
                    " or ".join(entity.brand_options)
                    + f": planned as any {entity.category.replace('_', ' ')} place, "
                    "with these brands kept as the preference."
                )
        return merged

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
    def _unknown_explicit_brand(text: str, entities: list[_Entity]) -> str | None:
        patterns = (
            r"must be ([a-z0-9 ]+?)(?: specifically| and| plus| but|$)",
            r"need ([a-z0-9 ]+?) specifically(?: and| plus| but|$)",
            r"prefer ([a-z0-9 ]+?)(?: but| and| plus|$)",
        )
        # Clause by clause: normalising strips the commas, and "prefer
        # FairPrice, don't want to walk much" then named a brand called
        # "fairprice don t want to walk much".
        clauses = [normalize_text(clause) for clause in re.split(r"[,;.!?]", text)]
        for pattern in patterns:
            match = next((found for clause in clauses if (found := re.search(pattern, clause))), None)
            if match:
                value = match.group(1).strip()
                recognized = any(
                    value in {
                        entity.phrase,
                        normalize_text(entity.brand or ""),
                        *(normalize_text(option) for option in entity.brand_options),
                    }
                    for entity in entities
                )
                if value and value not in CATEGORY_PHRASES and not recognized:
                    return value
        return None

    @staticmethod
    def _is_optional(normalized: str, entity: _Entity, entity_count: int) -> bool:
        phrase = re.escape(entity.phrase)
        if re.search(rf"\b{phrase}\b(?: maybe)?(?: is)? if (?:convenient|possible)", normalized):
            return True
        if re.search(rf"\bmaybe (?:(?:a|an|some|get|grab|buy) )?{phrase}\b|\b{phrase} maybe\b", normalized):
            return True
        if re.search(rf"skip (?:the )?\b{phrase}\b", normalized):
            return True
        if re.search(rf"\b{phrase}\b.{{0,25}}\boptional\b", normalized):
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
    def _preferences(normalized: str, prepared: PreparedRequest) -> IntentPreferences:
        max_detour = None
        max_detour_is_hard = False
        detour_match = re.search(
            r"(?:less than|under|no more than|max(?:imum)?|within|more than)\s*(\d+(?:\.\d+)?)\s*(?:min|minute)",
            normalized,
        )
        if detour_match:
            max_detour = float(detour_match.group(1))
            window = normalized[max(0, detour_match.start() - 18):detour_match.end() + 8]
            max_detour_is_hard = prepared.strict or bool(
                re.search(r"\b(max(?:imum)?|must|strict|no more than)\b", window)
                or re.search(r"\bunder\s+\d+(?:\.\d+)?\s*(?:min|minute)s?\s+max\b", window)
            ) and not any(term in window for term in ("try", "prefer", "ideally"))
        walking = WalkingTolerance.STANDARD
        if any(term in normalized for term in (
            "minimal walking", "minimise walking", "minimize walking", "less walking", "as little walking",
            "dont want to walk", "don t want to walk", "do not want to walk", "not much walking",
            "not too much walking", "little walking", "hate walking", "dont like walking", "don t like walking",
        )):
            walking = WalkingTolerance.MINIMAL
        elif any(term in normalized for term in ("dont mind walking", "don t mind walking")):
            walking = WalkingTolerance.HIGH
        max_walking = None
        max_walking_is_hard = False
        walking_match = re.search(r"(?:walk|walking).{0,12}(\d+(?:\.\d+)?)\s*(?:min|minute)", normalized)
        if walking_match:
            max_walking = float(walking_match.group(1))
            walking_window = normalized[max(0, walking_match.start() - 18):walking_match.end() + 8]
            max_walking_is_hard = prepared.strict or bool(
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
            arrival_by=prepared.arrival_by,
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
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.deterministic = DeterministicIntentParser(repository, clock)
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

    def _valid_categories(self) -> set[str]:
        # The leaf categories plus the middle ones a brand or the catalog
        # serves: fast_food has its own outlets (and fried_chicken under it),
        # and the parser reads "fast food", "food" and McDonald's as it, so
        # leaving it out made every such parse a 422 at optimisation. Only
        # the top-level groups ("food_drink", "retail") stay too broad.
        valid = set(self.repository.category_catalog())
        valid.update(
            entry["slug"] for entry in self.repository.category_catalog_entries()
            if entry["parent_slug"]
        )
        valid.update(
            category for brand in self.repository.brand_catalog() for category in brand["categories"]
        )
        return valid

    def _canonical_brand_list(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            brand = self.repository.resolve_brand(value)
            # An unknown name is kept as written: excluding or preferring a
            # brand the catalog lacks is harmless, dropping the words is not.
            name = brand["canonical_name"] if brand else value
            if name not in result:
                result.append(name)
        return result

    def _canonicalize(self, intent: IntentV1) -> tuple[IntentV1 | None, list[str]]:
        valid_categories = self._valid_categories()
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
                try:
                    errand = IntentErrand(
                        category=category,
                        required=item.required,
                        exact_brand=exact["canonical_name"] if exact else None,
                        preferred_brand=preferred["canonical_name"] if preferred else None,
                        exact_place=place["display_name"] if place else None,
                        substitutes_allowed=item.substitutes_allowed,
                        discovery_concept=item.discovery_concept,
                        open_need=item.open_need,
                        discovery_category=item.discovery_category,
                        excluded_brands=self._canonical_brand_list(item.excluded_brands),
                        brand_options=self._canonical_brand_list(item.brand_options),
                        modifiers=list(item.modifiers),
                        requested_concept=item.requested_concept,
                    )
                except ValidationError:
                    # Two spellings of one brand, asked for and excluded.
                    unresolved.append(f"{brand['canonical_name']} both wanted and excluded" if brand else item.category)
                    continue
                target.append(errand)
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
