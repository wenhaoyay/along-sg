"""The request parser on what people actually type: negation, typos,
Singlish and Chinese, clock times and filler words. Each case was a
reviewed mis-parse; the round-trip tests pin that whatever the parser
resolves, /api/optimize-intent accepts."""

from __future__ import annotations

import itertools
import json
import random
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.intent_models import IntentErrand, IntentStatus, IntentV1
from app.main import create_app
from app.services.intent_parser import (
    ATM_CATEGORY,
    SINGAPORE,
    DeterministicIntentParser,
    IntentParserService,
)

MORNING = datetime(2026, 10, 23, 10, 0, tzinfo=SINGAPORE)
NIGHT = datetime(2026, 10, 23, 21, 0, tzinfo=SINGAPORE)
PHRASINGS = json.loads(
    (Path(__file__).parents[1] / "data" / "phrasing-evaluation.json").read_text(encoding="utf-8")
)["cases"]


@pytest.fixture
def parser(repository):
    return DeterministicIntentParser(repository, clock=lambda: MORNING)


def errands(response):
    assert response.intent is not None, response
    return response.intent.required_errands + response.intent.optional_errands


def only(response) -> IntentErrand:
    found = errands(response)
    assert len(found) == 1, found
    return found[0]


# ------------------------------------------------------------------ negation

def test_not_a_brand_is_never_that_brand(parser):
    errand = only(parser.parse("not McDonald's"))
    # McDonald's own errand category: burgers in the built catalog, fast
    # food in the small seed one the tests run on.
    assert errand.category in {"burgers", "fast_food"}
    assert errand.exact_brand is None and errand.preferred_brand is None
    assert errand.excluded_brands == ["McDonald's"]
    assert errand.substitutes_allowed


def test_no_kfc_any_burger_is_burgers_without_kfc(parser):
    errand = only(parser.parse("no KFC, any burger"))
    assert errand.category == "burgers"
    assert errand.exact_brand is None
    assert errand.excluded_brands == ["KFC"]


def test_fast_food_but_not_mcdonalds_validates(parser, repository):
    response = parser.parse("fast food but not McDonald's")
    errand = only(response)
    assert errand.category == "fast_food"
    assert errand.excluded_brands == ["McDonald's"]
    canonical, unresolved = IntentParserService(repository).validate_intent(response.intent)
    assert unresolved == [] and canonical is not None
    assert canonical.required_errands[0].excluded_brands == ["McDonald's"]


@pytest.mark.parametrize("text, brand", [
    ("fried chicken without KFC", "KFC"),
    ("pharmacy except Watsons", "Watsons"),
    ("coffee but avoid Starbucks", "Starbucks"),
    ("groceries, anything but FairPrice", "FairPrice"),
    ("burgers other than McDonalds", "McDonald's"),
    ("coffee, I don't want Starbucks", "Starbucks"),
])
def test_negation_words(parser, text, brand):
    errand = only(parser.parse(text))
    assert errand.excluded_brands == [brand]
    assert errand.exact_brand is None and errand.preferred_brand is None


def test_guardian_not_watsons(parser):
    errand = only(parser.parse("Guardian not Watsons"))
    assert errand.category == "pharmacy"
    assert errand.exact_brand == "Guardian"
    assert errand.excluded_brands == ["Watsons"]


def test_exclusion_goes_to_the_errand_it_could_serve(parser):
    response = parser.parse("groceries and coffee, not Starbucks")
    by_category = {item.category: item for item in errands(response)}
    assert by_category["coffee"].excluded_brands == ["Starbucks"]
    assert by_category["groceries"].excluded_brands == []


def test_if_not_offers_a_fallback_rather_than_excluding(parser):
    errand = only(parser.parse("KFC, if not Popeyes"))
    assert errand.excluded_brands == []
    assert errand.brand_options == ["KFC", "Popeyes"]


# ------------------------------------------------------------------- typos

@pytest.mark.parametrize("text, category, typed, understood", [
    ("buy panadl", "pharmacy", "panadl", "panadol"),
    ("groseries", "groceries", "groseries", "groceries"),
    ("pharmcy", "pharmacy", "pharmcy", "pharmacy"),
    ("starbuck", "coffee", "starbuck", "starbucks"),
])
def test_near_spellings_are_read_with_lower_confidence(parser, text, category, typed, understood):
    response = parser.parse(text)
    assert only(response).category == category
    assert [(item.typed, item.understood_as) for item in response.spelling_corrections] == [(typed, understood)]
    assert response.intent.confidence < 0.9


@pytest.mark.parametrize("text", [
    "take a break", "batteries", "good morning", "hello", "tell me a joke", "cofe", "teaa",
    "money changer",
])
def test_spelling_correction_stays_conservative(parser, text):
    response = parser.parse(text)
    assert not response.spelling_corrections
    assert response.status != IntentStatus.RESOLVED


def test_exact_words_are_not_corrected(parser):
    response = parser.parse("coffee and groceries")
    assert not response.spelling_corrections
    assert response.intent.confidence == pytest.approx(0.98)


# --------------------------------------------------------- Singlish/Chinese

@pytest.mark.parametrize("text, categories", [
    ("kopi", ["coffee"]),
    ("teh peng", ["coffee"]),
    ("makan", ["restaurants"]),
    ("牛奶", ["groceries"]),
    ("买牛奶", ["groceries"]),
    ("药", ["pharmacy"]),
    ("药房", ["pharmacy"]),
    ("咖啡", ["coffee"]),
    ("奶茶", ["bubble_tea"]),
    ("珍珠奶茶", ["bubble_tea"]),
    ("🧋", ["bubble_tea"]),
    ("咖啡和奶茶", ["coffee", "bubble_tea"]),
    ("buy 牛奶 and panadol", ["groceries", "pharmacy"]),
    ("dinner", ["restaurants"]),
    ("ice cream", ["dessert"]),
])
def test_local_and_chinese_words(parser, text, categories):
    response = parser.parse(text)
    assert [item.category for item in errands(response)] == categories
    assert response.unresolved_terms == []


@pytest.mark.parametrize("text", ["ATM", "取钱", "withdraw cash"])
def test_atm_requests_go_to_the_atm_category_and_keep_the_concept(parser, text):
    errand = only(parser.parse(text))
    assert errand.category == ATM_CATEGORY
    assert errand.requested_concept == "atm"


def test_post_office_is_its_own_category_with_the_concept_kept(parser):
    response = parser.parse("post office")
    errand = only(response)
    assert errand.category == "post_office"
    assert errand.requested_concept == "post_office"
    assert not any("parcel" in note for note in response.notes)


@pytest.mark.parametrize("text, category", [
    ("tapau makan", "restaurants"), ("da bao some kopi", "coffee"), ("dabao dinner", "restaurants"),
])
def test_takeaway_is_a_modifier_on_a_food_errand(parser, text, category):
    errand = only(parser.parse(text))
    assert errand.category == category
    assert errand.modifiers == ["takeaway"]


def test_takeaway_alone_is_not_an_errand(parser):
    assert parser.parse("tapau").status != IntentStatus.RESOLVED


def test_words_that_cannot_be_represented_are_reported(parser):
    response = parser.parse("panadol and 自行车")
    assert [item.category for item in errands(response)] == ["pharmacy"]
    assert response.unresolved_terms == ["自行车"]
    assert "自行车" in response.clarification_question


def test_only_unrepresentable_words_is_unresolved_with_them(parser):
    response = parser.parse("自行车")
    assert response.status == IntentStatus.UNRESOLVED
    assert response.unresolved_terms == ["自行车"]


def test_accented_brand_letters_are_not_foreign(parser):
    response = parser.parse("KOI Thé")
    assert only(response).category == "bubble_tea"
    assert response.unresolved_terms == []


# ------------------------------------------------------------------- times

@pytest.mark.parametrize("text, expected", [
    ("coffee before 7pm", datetime(2026, 10, 23, 19, 0, tzinfo=SINGAPORE)),
    ("coffee by 6:30pm", datetime(2026, 10, 23, 18, 30, tzinfo=SINGAPORE)),
    ("coffee, arrive by 6pm", datetime(2026, 10, 23, 18, 0, tzinfo=SINGAPORE)),
    ("coffee before 19:00", datetime(2026, 10, 23, 19, 0, tzinfo=SINGAPORE)),
    ("coffee, need to be there by 9am", datetime(2026, 10, 24, 9, 0, tzinfo=SINGAPORE)),
    ("coffee by 6:30", datetime(2026, 10, 23, 18, 30, tzinfo=SINGAPORE)),
    ("coffee and arrive by 2026-10-25 08:15", datetime(2026, 10, 25, 8, 15, tzinfo=SINGAPORE)),
])
def test_clock_times_become_an_aware_arrival(parser, text, expected):
    response = parser.parse(text)
    assert only(response).category == "coffee"
    arrival = response.intent.preferences.arrival_by
    assert arrival == expected
    assert arrival.utcoffset() == expected.utcoffset()


def test_a_time_already_past_today_means_tomorrow(repository):
    late = DeterministicIntentParser(repository, clock=lambda: NIGHT)
    arrival = late.parse("groceries before 7pm").intent.preferences.arrival_by
    assert arrival == datetime(2026, 10, 24, 19, 0, tzinfo=SINGAPORE)


@pytest.mark.parametrize("text", ["arrive by 6pm", "before 7pm", "by 19:30"])
def test_a_time_alone_is_not_an_errand(parser, text):
    response = parser.parse(text)
    assert response.intent is None
    assert response.status == IntentStatus.NEEDS_CLARIFICATION


# ------------------------------------------------------- modifiers / filler

def test_strictly_keeps_the_limit_hard_and_is_not_an_errand(parser):
    response = parser.parse("coffee, max 5 min extra, strictly")
    assert only(response).category == "coffee"
    assert response.intent.preferences.max_detour_minutes == 5
    assert response.intent.preferences.max_detour_is_hard


def test_strictly_makes_a_soft_limit_hard(parser):
    soft = parser.parse("coffee within 10 min").intent.preferences
    hard = parser.parse("coffee within 10 min, strictly").intent.preferences
    assert not soft.max_detour_is_hard
    assert hard.max_detour_is_hard


@pytest.mark.parametrize("text", [
    "groceries please lah", "pls get groceries ah", "groceries leh", "quickly get groceries",
])
def test_filler_words_never_become_errands(parser, text):
    assert [item.category for item in errands(parser.parse(text))] == ["groceries"]


@pytest.mark.parametrize("text", [
    "groceries, and coffee if convenient", "groceries and maybe coffee", "groceries, coffee if possible",
])
def test_optional_errands_are_optional(parser, text):
    intent = parser.parse(text).intent
    assert [item.category for item in intent.required_errands] == ["groceries"]
    assert [item.category for item in intent.optional_errands] == ["coffee"]
    assert intent.optional_errands[0].required is False


def test_either_brand_is_one_errand_with_both_kept(parser):
    response = parser.parse("starbucks or toast box")
    errand = only(response)
    assert errand.category == "coffee"
    assert errand.brand_options == ["Starbucks", "Toast Box"]
    assert errand.exact_brand is None and errand.preferred_brand is None
    assert response.notes


# ------------------------------------------------------------- API surface

def test_api_reads_errands_after_go_to_and_drops_nothing(tmp_path: Path):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "api.db"))
    with TestClient(app) as client:
        def parse(text):
            return client.post("/api/intent/parse", json={"text": text}).json()

        post = parse("go to the post office")
        assert post["status"] == "resolved"
        assert post["intent"]["required_errands"][0]["category"] == "post_office"
        assert post["journey_mentions"] == []

        strict = parse("bubble tea, max 10 min extra, strictly pls")
        assert [item["category"] for item in strict["intent"]["required_errands"]] == ["bubble_tea"]
        assert strict["intent"]["preferences"]["max_detour_is_hard"] is True

        time_only = parse("arrive by 6pm")
        assert time_only["intent"] is None

        partial = parse("panadol and 自行车")
        assert partial["unresolved_terms"] == ["自行车"]

        typo = parse("buy panadl")
        assert typo["spelling_corrections"] == [{"typed": "panadl", "understood_as": "panadol"}]

        home = parse("coffee then go home to Bishan")
        assert home["journey_mentions"]


# ------------------------------------------------- parse -> validate round trip

SUBJECTS = (
    "groceries", "panadol", "coffee", "kopi", "teh", "bubble tea", "🧋", "奶茶", "牛奶", "药房",
    "KFC", "McDonald's", "Starbucks", "Guardian", "Watsons", "FairPrice", "fast food", "food",
    "dinner", "makan", "ice cream", "post office", "ATM", "取钱", "cake", "snacks", "haircut",
    "printer ink", "cat food", "flowers", "fried chicken", "burgers", "toast box", "koi",
)
TAILS = (
    "", " please", " lah", ", strictly under 10 min", " before 7pm", " if convenient",
    ", not McDonald's", " but not Watsons", ", no KFC", " by 18:30", ", minimal walking",
    ", tapau", " maybe",
)


def _generated_phrasings():
    for first, tail in itertools.product(SUBJECTS, TAILS):
        yield first + tail
    # Every pair would be 1,100 more parses; a fixed sample keeps CI quick.
    pairs = random.Random(20261023).sample(list(itertools.combinations(SUBJECTS, 2)), 150)
    for (first, second), joint in zip(pairs, itertools.cycle((" and ", " or ", ", then "))):
        yield first + joint + second


def test_every_resolved_parse_validates(repository):
    service = IntentParserService(repository)
    parser = DeterministicIntentParser(repository, clock=lambda: MORNING)
    texts = [*_generated_phrasings(), *(case["text"] for case in PHRASINGS)]
    assert len(texts) > 650
    resolved = 0
    for text in texts:
        response = parser.parse(text)
        if response.status != IntentStatus.RESOLVED:
            continue
        resolved += 1
        canonical, unresolved = service.validate_intent(response.intent)
        assert unresolved == [], (text, unresolved)
        assert canonical is not None
        again, unresolved_again = service.validate_intent(canonical)
        assert unresolved_again == [] and again == canonical, text
    assert resolved > 450


def test_every_evaluation_phrasing_round_trips_through_the_api(tmp_path: Path):
    app = create_app(Settings(onemap_mock=True, database_path=tmp_path / "roundtrip.db",
                              llm_intent_enabled=False, discovery_live_enabled=False))
    with TestClient(app) as client:
        service = app.state.intent_parser
        for case in PHRASINGS:
            body = client.post("/api/intent/parse", json={"text": case["text"]}).json()
            if body.get("intent") is None:
                continue
            canonical, unresolved = service.validate_intent(IntentV1.model_validate(body["intent"]))
            assert unresolved == [], (case["text"], unresolved)
            assert canonical is not None
