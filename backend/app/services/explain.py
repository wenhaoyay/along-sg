"""Why an option is shown, said from the comparison that was actually made.

The sentence used to be a fixed string per label: "Lowest combined added time,
walking and transfer impact among the evaluated options." It said that even
when the option listed right under the pick was quicker and walked less, which
is the one thing a comparison product cannot get wrong. Every claim here is
checked against the other routed options before it is made.
"""

from __future__ import annotations

from app.domain import OptimizationPreferences, ScoredCandidate
from app.presentation import category_label, hub_display_name

# Differences smaller than these are not worth a sentence.
TRAVEL_EPSILON_MINUTES = 0.5
WALKING_EPSILON_METRES = 50.0


def option_name(candidate: ScoredCandidate) -> str:
    return " then ".join(hub_display_name(stop) for stop in candidate.ordered_stops)


def _minutes(value: float) -> str:
    rounded = round(value)
    if rounded < 1:
        return "under a minute"
    return f"{rounded} min"


def _metres(value: float) -> str:
    return f"{round(value / 10) * 10:.0f} m"


def _stop_set(candidate: ScoredCandidate) -> frozenset[int]:
    return frozenset(stop.id for stop in candidate.ordered_stops)


def _has_brand(candidate: ScoredCandidate, category: str, brand: str) -> bool:
    return any(
        category in candidate.option.categories_at(stop.id)
        and any(store.canonical_brand == brand and category in store.all_categories for store in stop.stores)
        for stop in candidate.option.stops
    )


def _preferred_brands_met(candidate: ScoredCandidate, preferences: OptimizationPreferences) -> list[str]:
    return [
        brand
        for category, brand in preferences.preferred_brands
        if category in candidate.option.required_categories and _has_brand(candidate, category, brand)
    ]


def missing_preferred_brands(candidate: ScoredCandidate, preferences: OptimizationPreferences) -> list[str]:
    return [
        brand
        for category, brand in preferences.preferred_brands
        if category in candidate.option.required_categories and not _has_brand(candidate, category, brand)
    ]


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def explain_best(
    winner: ScoredCandidate,
    pool: list[ScoredCandidate],
    preferences: OptimizationPreferences,
) -> str:
    others: dict[frozenset[int], ScoredCandidate] = {}
    # A two-stop plan is routed in both orders; compare against its better one.
    for item in pool:
        key = _stop_set(item)
        if key == _stop_set(winner):
            continue
        kept = others.get(key)
        if kept is None or item.incremental_travel_minutes < kept.incremental_travel_minutes:
            others[key] = item
    rivals = list(others.values())
    if not rivals:
        return "The only place we could route that covers everything you asked for."

    compared = len(rivals) + 1
    quickest = min(rivals, key=lambda item: item.incremental_travel_minutes)
    travel_gap = winner.incremental_travel_minutes - quickest.incremental_travel_minutes
    if travel_gap <= TRAVEL_EPSILON_MINUTES:
        least_walk = min(item.incremental_walking_distance_m for item in rivals)
        fewest_changes = min(item.incremental_transfers for item in rivals)
        wins = ["the least extra travel"]
        if winner.incremental_walking_distance_m <= least_walk + WALKING_EPSILON_METRES:
            wins.append("the least extra walking")
        if winner.incremental_transfers < fewest_changes:
            wins.append("the fewest changes")
        return f"Of the {compared} places compared, it has {_join(wins)}."

    rival_name = option_name(quickest)
    gap = _minutes(travel_gap)
    winner_brands = _preferred_brands_met(winner, preferences)
    rival_brands = set(_preferred_brands_met(quickest, preferences))
    brand_edge = [brand for brand in winner_brands if brand not in rival_brands]
    if brand_edge:
        brands = _join(brand_edge)
        return f"It has {brands}, which you prefer. {rival_name} is {gap} quicker but has no {brands}."
    if winner.option.consolidated and not quickest.option.consolidated:
        return f"Everything is in one place. {rival_name} is {gap} quicker but means two separate stops."
    if winner.incremental_transfers < quickest.incremental_transfers:
        extra = quickest.incremental_transfers - winner.incremental_transfers
        changes = "change" if extra == 1 else "changes"
        return f"{rival_name} is {gap} quicker but needs {extra} more {changes}."
    walk_gap = quickest.incremental_walking_distance_m - winner.incremental_walking_distance_m
    if walk_gap >= WALKING_EPSILON_METRES:
        return f"{rival_name} is {gap} quicker but walks {_metres(walk_gap)} more."
    return (
        f"{rival_name} is {gap} quicker. This one ranks first because its shop and "
        "location details are more complete, so it is less likely to surprise you."
    )


def explain_alternative(
    label_key: str,
    candidate: ScoredCandidate,
    best: ScoredCandidate | None,
    preferences: OptimizationPreferences,
) -> str:
    if candidate.match_classification == "partial_option" and candidate.option.omitted_categories:
        skipped = _join([category_label(item).lower() for item in candidate.option.omitted_categories])
        saving = ""
        if best is not None:
            saved = best.incremental_detour_minutes - candidate.incremental_detour_minutes
            if saved >= 1:
                saving = f", and gets you there {_minutes(saved)} sooner"
        return f"Skips the {skipped}{saving}."
    if candidate.match_classification == "substitute" and candidate.option.substituted_categories:
        swaps = _join([
            f"{category_label(substitute).lower()} instead of {category_label(requested).lower()}"
            for requested, substitute in candidate.option.substituted_categories
        ])
        sooner = ""
        if best is not None:
            saved = best.incremental_detour_minutes - candidate.incremental_detour_minutes
            if saved >= 1:
                sooner = f", and gets you there {_minutes(saved)} sooner"
        return f"A substitute: {swaps}{sooner}."
    if best is None:
        return ""
    travel_gap = best.incremental_travel_minutes - candidate.incremental_travel_minutes
    walk_gap = best.incremental_walking_distance_m - candidate.incremental_walking_distance_m
    costs = []
    if candidate.incremental_transfers > best.incremental_transfers:
        extra = candidate.incremental_transfers - best.incremental_transfers
        costs.append(f"{extra} more {'change' if extra == 1 else 'changes'}")
    if -walk_gap >= WALKING_EPSILON_METRES:
        costs.append(f"{_metres(-walk_gap)} more walking")
    missing = missing_preferred_brands(candidate, preferences)
    if missing:
        costs.append(f"no {_join(missing)}")
    cost = f", but {_join(costs)}" if costs else ""
    if label_key == "fastest" and travel_gap > TRAVEL_EPSILON_MINUTES:
        return f"{_minutes(travel_gap)} less travel than the top pick{cost}."
    if label_key == "least_walking" and walk_gap >= WALKING_EPSILON_METRES:
        slower = ""
        if -travel_gap > TRAVEL_EPSILON_MINUTES:
            slower = f", but {_minutes(-travel_gap)} more travel"
        return f"{_metres(walk_gap)} less walking than the top pick{slower}."
    return ""
