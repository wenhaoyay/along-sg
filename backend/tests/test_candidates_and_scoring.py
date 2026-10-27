from __future__ import annotations

from app.config import ScoringWeights
from app.domain import CandidateOption, Coordinate, Hub, RouteResult, ScoredCandidate, Store
from app.services.candidates import generate_candidates, prune_candidates
from app.services.optimizer import calculate_score, rank_recommendations


def test_one_errand_candidate_generation_only_returns_matching_hubs(repository) -> None:
    candidates = generate_candidates(repository, ("electronics",))

    assert candidates
    assert all("electronics" in candidate.stops[0].categories for candidate in candidates)
    assert all(len(candidate.stops) == 1 for candidate in candidates)
    assert all(not candidate.consolidated for candidate in candidates)


def test_scoring_uses_central_configurable_weights() -> None:
    weights = ScoringWeights(detour=2.0, walking=0.5, transfer=10.0)

    assert calculate_score(5, 4, 1, weights) == 22.0


def test_pruning_is_bounded_and_orders_by_geometric_detour() -> None:
    origin = Coordinate(1.4052, 103.9024)
    destination = Coordinate(1.3043, 103.8322)
    near = Hub(1, "Near corridor", Coordinate(1.3509, 103.8488), (Store("A", "parcel"),))
    far = Hub(2, "Far east", Coordinate(1.3526, 103.9447), (Store("B", "parcel"),))
    candidates = [
        CandidateOption((far,), ("parcel",), False),
        CandidateOption((near,), ("parcel",), False),
    ]

    pruned = prune_candidates(candidates, origin, destination, max_candidates=1, max_detour_km=50)

    assert len(pruned) == 1
    assert pruned[0].stops[0].name == "Near corridor"
    assert pruned[0].straight_line_detour_km >= 0


def _scored(name: str, detour: float, walking: float, score: float) -> ScoredCandidate:
    hub = Hub(hash(name), name, Coordinate(1.33, 103.84), (Store("Store", "parcel"),))
    option = CandidateOption((hub,), ("parcel",), False)
    route = RouteResult(30 + detour, 5 + walking, 500, 0)
    return ScoredCandidate(option, (hub,), route, detour, walking, 0, score)


def test_recommendation_ranking_has_distinct_objectives() -> None:
    balanced = _scored("Balanced", detour=5, walking=3, score=7)
    fast = _scored("Fast", detour=2, walking=8, score=9)
    short_walk = _scored("Short walk", detour=9, walking=1, score=10)

    ranked = rank_recommendations([fast, balanced, short_walk])

    assert ranked["best_overall"].ordered_stops[0].name == "Balanced"
    assert ranked["fastest"].ordered_stops[0].name == "Fast"
    assert ranked["least_walking"].ordered_stops[0].name == "Short walk"

