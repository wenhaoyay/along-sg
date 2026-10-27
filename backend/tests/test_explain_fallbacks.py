"""The sentence under a pick that is not a full match says why it is not."""

from types import SimpleNamespace

from app.domain import OptimizationPreferences
from app.services.explain import explain_alternative, explain_best


def candidate(classification, required=(), omitted=(), substituted=()):
    option = SimpleNamespace(
        required_categories=tuple(required),
        omitted_categories=tuple(omitted),
        substituted_categories=tuple(substituted),
    )
    return SimpleNamespace(match_classification=classification, option=option)


PREFS = OptimizationPreferences()


def test_partial_names_the_closed_errand():
    winner = candidate("partial_option", required=["groceries"], omitted=["pharmacy"])
    assert explain_best(winner, [winner], PREFS, frozenset({"pharmacy"})) == (
        "No pharmacy on the way is open when you'd get there, so this covers the supermarket only."
    )


def test_partial_without_a_closure_does_not_claim_one():
    winner = candidate("partial_option", required=["groceries"], omitted=["atm"])
    sentence = explain_best(winner, [winner], PREFS)
    assert sentence == "No stop on the way covers the ATM too, so this covers the supermarket only."
    assert "open" not in sentence


def test_substitute_says_what_it_stands_in_for():
    winner = candidate("substitute", required=["convenience"], substituted=[("groceries", "convenience")])
    assert explain_best(winner, [winner], PREFS, frozenset({"groceries"})) == (
        "No supermarket on the way is open when you'd get there, so this is a convenience store instead."
    )


def test_a_lone_pick_without_the_preferred_brand_names_it():
    winner = candidate("without_preferred_brand", required=["groceries"])
    winner.option.stops = ()
    winner.ordered_stops = ()
    prefs = OptimizationPreferences(preferred_brands=(("groceries", "FairPrice"),))
    assert explain_best(winner, [winner], prefs) == (
        "The only place we could route that covers everything you asked for, though it has no FairPrice."
    )


def test_alternative_uses_a_singular_place():
    option = candidate("partial_option", required=["groceries"], omitted=["post_office"])
    assert explain_alternative("partial_groceries", option, None, PREFS) == "Skips the post office."
