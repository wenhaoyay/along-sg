from __future__ import annotations

from datetime import datetime

from app.domain import CandidateFallback, Coordinate, Hub, OptimizationPreferences, RouteResult, ScoredCandidate
from app.intent_models import (
    IntentV1,
    TransferTolerance,
    Urgency,
    WalkingTolerance,
)
from app.services.optimizer import Optimizer
from app.poi_taxonomy import NEAR_MISS_SUBSTITUTES


def preferences_from_intent(intent: IntentV1) -> OptimizationPreferences:
    errands = intent.required_errands + intent.optional_errands
    walking_multipliers = {
        WalkingTolerance.MINIMAL: 2.25,
        WalkingTolerance.LOW: 1.5,
        WalkingTolerance.STANDARD: 1.0,
        WalkingTolerance.HIGH: 0.55,
    }
    transfer_multipliers = {
        TransferTolerance.NO_EXTRA: 2.5,
        TransferTolerance.PREFER_FEWER: 1.75,
        TransferTolerance.STANDARD: 1.0,
    }
    urgency_multipliers = {
        Urgency.NORMAL: 1.0,
        Urgency.SOON: 1.25,
        Urgency.URGENT: 1.6,
    }
    return OptimizationPreferences(
        exact_brands=tuple(
            (item.category, item.exact_brand)
            for item in errands
            if item.exact_brand is not None
        ),
        exact_places=tuple(
            (item.category, item.exact_place)
            for item in errands
            if item.exact_place is not None
        ),
        preferred_brands=tuple(
            (item.category, item.preferred_brand)
            for item in errands
            if item.preferred_brand is not None
        ),
        max_detour_minutes=intent.preferences.max_detour_minutes,
        max_extra_walking_minutes=intent.preferences.max_extra_walking_minutes,
        max_additional_transfers=intent.preferences.max_additional_transfers,
        prefer_consolidated_stops=intent.preferences.prefer_consolidated_stops,
        detour_weight_multiplier=urgency_multipliers[intent.preferences.urgency],
        walking_weight_multiplier=walking_multipliers[
            intent.preferences.walking_tolerance
        ],
        transfer_weight_multiplier=transfer_multipliers[
            intent.preferences.transfer_tolerance
        ],
        arrival_by=intent.preferences.arrival_by,
        max_detour_is_hard=intent.preferences.max_detour_is_hard,
        max_extra_walking_is_hard=intent.preferences.max_extra_walking_is_hard,
        max_additional_transfers_is_hard=intent.preferences.max_additional_transfers_is_hard,
    )


def _fallbacks(intent: IntentV1) -> tuple[CandidateFallback, ...]:
    errands = intent.required_errands + intent.optional_errands
    requested = tuple(item.category for item in errands)
    fallbacks: list[CandidateFallback] = []

    for item in errands:
        if not item.substitutes_allowed or item.exact_brand or item.exact_place:
            continue
        substitutes = NEAR_MISS_SUBSTITUTES.get(item.category, ())
        if not substitutes:
            continue
        substitute = substitutes[0]
        categories = tuple(substitute if category == item.category else category for category in requested)
        fallbacks.append(CandidateFallback(
            categories=categories,
            match_classification="easier_alternative",
            requested_categories=requested,
            substituted_categories=((item.category, substitute),),
            exact_brands=tuple(
                (errand.category, errand.exact_brand)
                for errand in errands
                if errand.category != item.category and errand.exact_brand
            ),
            exact_places=tuple(
                (errand.category, errand.exact_place)
                for errand in errands
                if errand.category != item.category and errand.exact_place
            ),
        ))

    if len(errands) == 2:
        for item in errands:
            fallbacks.append(CandidateFallback(
                categories=(item.category,),
                match_classification="partial_option",
                requested_categories=requested,
                omitted_categories=tuple(category for category in requested if category != item.category),
                exact_brands=((item.category, item.exact_brand),) if item.exact_brand else (),
                exact_places=((item.category, item.exact_place),) if item.exact_place else (),
            ))
    return tuple(fallbacks)


async def optimize_intent(
    optimizer: Optimizer,
    origin: Coordinate,
    destination: Coordinate,
    intent: IntentV1,
    departure: datetime | None,
    extra_hubs: tuple[Hub, ...] = (),
    routing_call_offset: int = 0,
) -> tuple[
    RouteResult,
    dict[str, ScoredCandidate],
    dict[str, float | int | bool | str | None],
    list[str],
]:
    all_errands = intent.required_errands + intent.optional_errands
    categories = [item.category for item in all_errands]
    baseline, recommendations, diagnostics = await optimizer.optimize(
        origin,
        destination,
        categories,
        departure,
        preferences_from_intent(intent),
        fallbacks=_fallbacks(intent),
        extra_hubs=extra_hubs,
        routing_call_offset=routing_call_offset,
    )
    primary = recommendations.get("best_overall")
    optimized_categories = (
        list(primary.option.required_categories)
        if primary and primary.match_classification == "partial_option"
        else categories
    )
    return baseline, recommendations, diagnostics, optimized_categories
