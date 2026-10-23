"""Presentation regressions for the V0.7.7 recommendation work.

An option is only worth offering if it is a choice. The ranking dedupe keyed on
stop identity, so two different buildings always both survived it - a live
Punggol-to-Orchard run returned +36.0 min and +35.9 min for different malls and
asked the user to pick. Spending someone's attention on a difference they
cannot act on also invites them to distrust the ranking that produced it.
"""

from __future__ import annotations

def _scored(stop_ids, detour, walking_m, transfers, score):
    """A ScoredCandidate stand-in carrying only what ranking reads."""
    from types import SimpleNamespace

    return SimpleNamespace(
        ordered_stops=tuple(SimpleNamespace(id=stop_id) for stop_id in stop_ids),
        incremental_detour_minutes=detour,
        incremental_walking_distance_m=walking_m,
        incremental_walking_minutes=walking_m / 80,
        incremental_transfers=transfers,
        overall_score=score,
    )


def test_an_alternative_six_seconds_apart_is_not_offered_as_a_choice() -> None:
    """Two different malls, indistinguishable journeys - offer one.

    A live Punggol-to-Orchard run returned best_overall at +36.0 min and
    fastest at +35.9 min for a different building. The signature keyed on stop
    identity, so both survived and the user was asked to choose between them.
    """
    from app.services.optimizer import rank_recommendations

    best = _scored([1], detour=36.0, walking_m=220, transfers=0, score=35.4)
    twin = _scored([2], detour=35.9, walking_m=221, transfers=0, score=35.6)

    ranked = rank_recommendations([best, twin])
    assert list(ranked) == ["best_overall"]
    assert ranked["best_overall"] is best


def test_a_genuinely_different_tradeoff_is_still_offered() -> None:
    from app.services.optimizer import rank_recommendations

    best = _scored([1], detour=36.0, walking_m=800, transfers=0, score=40.0)
    drier = _scored([2], detour=41.0, walking_m=90, transfers=0, score=41.0)

    ranked = rank_recommendations([best, drier])
    assert "best_overall" in ranked
    assert "least_walking" in ranked
    assert ranked["least_walking"] is drier


def test_walking_alone_can_make_an_option_distinct() -> None:
    """Same minutes, but a 400 m difference in walking is worth a choice."""
    from app.services.optimizer import rank_recommendations

    best = _scored([1], detour=30.0, walking_m=600, transfers=0, score=35.0)
    drier = _scored([2], detour=30.2, walking_m=150, transfers=0, score=36.0)

    ranked = rank_recommendations([best, drier])
    assert ranked.get("least_walking") is drier
