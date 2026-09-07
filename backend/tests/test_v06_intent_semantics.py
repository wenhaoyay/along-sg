from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.intent_models import IntentStatus
from app.services.intent_parser import DeterministicIntentParser


CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "intent_v1_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["prompt"][:45])
def test_semantic_intent_fixture(case, repository):
    response = DeterministicIntentParser(repository).parse(case["prompt"])
    assert response.status == IntentStatus(case["status"])
    if response.status != IntentStatus.RESOLVED:
        assert response.intent is None
        assert response.clarification_question
        return

    assert response.intent is not None
    assert [item.category for item in response.intent.required_errands] == case.get(
        "required", []
    )
    assert [item.category for item in response.intent.optional_errands] == case.get(
        "optional", []
    )
    exact = {
        item.category: item.exact_brand
        for item in response.intent.required_errands + response.intent.optional_errands
        if item.exact_brand
    }
    preferred = {
        item.category: item.preferred_brand
        for item in response.intent.required_errands + response.intent.optional_errands
        if item.preferred_brand
    }
    assert exact == case.get("exact", {})
    assert preferred == case.get("preferred", {})
    for key, expected in case.get("preferences", {}).items():
        actual = getattr(response.intent.preferences, key)
        if hasattr(actual, "value"):
            actual = actual.value
        elif hasattr(actual, "isoformat"):
            actual = actual.isoformat()
        assert actual == expected


def test_fixture_matrix_has_at_least_forty_prompts():
    assert len(CASES) >= 40
    assert len({case["prompt"] for case in CASES}) == len(CASES)
