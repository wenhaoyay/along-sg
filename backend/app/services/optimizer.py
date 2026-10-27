from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timedelta
from itertools import permutations
from zoneinfo import ZoneInfo

from app.config import DwellTimes, ScoringWeights
from app.db import HubRepository
from app.domain import (
    SINGAPORE_TZ,
    CandidateFallback,
    CandidateOption,
    Coordinate,
    Hub,
    OptimizationPreferences,
    RouteResult,
    ScoredCandidate,
)
from app.presentation import hub_data_quality
from app.providers.base import MapProvider, ProviderError, ProviderNoRouteError
from app.services.explain import explain_alternative, explain_best
from app.services.opening_hours import check_hours
from app.services.candidates import (
    CandidatePipelineResult,
    baseline_geometry,
    normalize_categories,
    staged_candidate_pipeline,
)
from app.discovery_models import DiscoverySearchContext


logger = logging.getLogger("journey_optimizer")


class RoutingBudgetExceeded(RuntimeError):
    pass


class RouteCache:
    """Small process-local LRU cache; keys include directed coordinates and time bucket."""

    def __init__(self, max_entries: int = 512, ttl_seconds: float = 300.0):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple[float, ...], tuple[float, RouteResult]] = OrderedDict()

    def get(self, key: tuple[float, ...]) -> RouteResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        created, result = entry
        if time.monotonic() - created > self.ttl_seconds:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return result

    def put(self, key: tuple[float, ...], result: RouteResult) -> None:
        self._entries[key] = (time.monotonic(), result)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


def calculate_score(
    detour_minutes: float,
    walking_minutes: float,
    transfers: int,
    weights: ScoringWeights,
    data_quality_score: float = 0.0,
) -> float:
    return round(
        detour_minutes * weights.detour
        + walking_minutes * weights.walking
        + transfers * weights.transfer
        - data_quality_score * weights.data_quality_bonus,
        3,
    )


def combine_routes(
    routes: list[RouteResult],
    dwell_minutes: float = 0.0,
    time_dependent: bool | None = None,
) -> RouteResult:
    return RouteResult(
        duration_minutes=round(
            sum(route.duration_minutes for route in routes) + dwell_minutes, 2
        ),
        walking_minutes=round(sum(route.walking_minutes for route in routes), 2),
        walking_distance_m=round(
            sum(route.walking_distance_m for route in routes), 1
        ),
        transfers=sum(route.transfers for route in routes),
        legs=tuple(
            replace(leg, segment_index=index)
            for index, route in enumerate(routes)
            for leg in route.legs
        ),
        provider=routes[0].provider if routes else "unknown",
        raw_metadata={
            "segments": len(routes),
            "travel_minutes": round(
                sum(route.duration_minutes for route in routes), 2
            ),
        },
        departure_time=routes[0].departure_time if routes else None,
        arrival_time=routes[-1].arrival_time if routes else None,
        dwell_minutes=round(dwell_minutes, 2),
        time_dependent=time_dependent,
    )


def rank_recommendations(
    candidates: list[ScoredCandidate],
) -> dict[str, ScoredCandidate]:
    if not candidates:
        raise ValueError("No candidates were evaluated")
    ranked = {
        "best_overall": min(
            candidates,
            key=lambda item: (
                item.overall_score,
                item.incremental_detour_minutes,
                item.incremental_walking_minutes,
            ),
        ),
        "fastest": min(
            candidates,
            key=lambda item: (
                item.incremental_detour_minutes,
                item.overall_score,
                item.incremental_walking_minutes,
            ),
        ),
        "least_walking": min(
            candidates,
            key=lambda item: (
                item.incremental_walking_minutes,
                item.incremental_detour_minutes,
                item.overall_score,
            ),
        ),
    }
    unique: dict[str, ScoredCandidate] = {}
    seen: set[tuple[tuple[int, ...], int, int, int]] = set()
    for key, item in ranked.items():
        signature = (
            tuple(stop.id for stop in item.ordered_stops),
            round(item.incremental_detour_minutes),
            round(item.incremental_walking_distance_m / 50),
            item.incremental_transfers,
        )
        if signature in seen:
            continue
        # The signature keys on stop identity, so two different buildings always
        # both survived it - including a pair six seconds apart. Offering those
        # as a choice spends the user's attention on a difference they cannot
        # act on, and invites them to distrust the ranking. `best_overall` is
        # always kept; a later option has to earn its place by differing.
        if key != "best_overall" and any(
            _outcomes_are_indistinguishable(item, kept) for kept in unique.values()
        ):
            continue
        # "Fastest" that is 0.2 min quicker for an extra change, or "Least
        # walking" that walks 20 m less, is not a choice worth offering.
        best = unique.get("best_overall")
        if best is not None and key == "fastest" and (
            best.incremental_detour_minutes - item.incremental_detour_minutes
            < INDISTINGUISHABLE_DETOUR_MINUTES
        ):
            continue
        if best is not None and key == "least_walking" and (
            best.incremental_walking_distance_m - item.incremental_walking_distance_m
            < INDISTINGUISHABLE_WALKING_METRES
            and best.incremental_walking_minutes - item.incremental_walking_minutes
            < INDISTINGUISHABLE_WALKING_MINUTES
        ):
            continue
        unique[key] = item
        seen.add(signature)
    return unique


# A different mall is a different answer only if the journey it produces differs
# by something a traveller would notice. Below these, it is noise.
# How many also-compared candidates are worth reporting. Enough to make the
# comparison legible on the map; beyond this the markers stop being readable and
# start being noise.
MAX_CONSIDERED_REPORTED = 6

INDISTINGUISHABLE_DETOUR_MINUTES = 2.0
# A one-errand option is shown beside full matches only if it saves this much travel.
PARTIAL_OPTION_MIN_SAVING_MINUTES = 5.0
INDISTINGUISHABLE_WALKING_METRES = 100.0
INDISTINGUISHABLE_WALKING_MINUTES = 1.5


def _outcomes_are_indistinguishable(
    candidate: ScoredCandidate, other: ScoredCandidate
) -> bool:
    return (
        candidate.incremental_transfers == other.incremental_transfers
        and abs(candidate.incremental_detour_minutes - other.incremental_detour_minutes)
        < INDISTINGUISHABLE_DETOUR_MINUTES
        and abs(
            candidate.incremental_walking_distance_m - other.incremental_walking_distance_m
        )
        < INDISTINGUISHABLE_WALKING_METRES
    )


def _relationship_explanation(relationship: str) -> str:
    return {
        "same_mall": "Both errands are consolidated inside the same mall",
        "same_place": "Both errands are consolidated at one physical place",
        "same_transport_hub": (
            "The stores are separate but within the same transport hub or station area"
        ),
        "nearby_separate_stores": (
            "The stores are nearby but remain separate physical stops"
        ),
        "separate_stops": "This option requires genuinely separate errand stops",
        "single_stop": "This option adds one errand stop",
    }.get(relationship, "This option adds an errand stop")


class Optimizer:
    def __init__(
        self,
        provider: MapProvider,
        repository: HubRepository,
        weights: ScoringWeights,
        max_candidates: int,
        max_straight_line_detour_km: float,
        dwell_times: DwellTimes | None = None,
        routing_soft_budget: int = 20,
        routing_hard_budget: int = 30,
        max_reasonable_detour_minutes: float = 45.0,
        corridor_km: float = 2.5,
        endpoint_radius_km: float = 2.0,
        max_transit_node_distance_m: float = 1200.0,
        max_hubs_per_category: int = 8,
        route_cache_max_entries: int = 512,
        route_cache_ttl_seconds: float = 300.0,
        departure_time_bucket_minutes: int = 1,
        routing_concurrency: int = 1,
    ):
        if routing_soft_budget < 1 or routing_hard_budget < routing_soft_budget:
            raise ValueError("Routing budgets must be positive and hard >= soft")
        self.provider = provider
        self.repository = repository
        self.weights = weights
        self.max_candidates = max_candidates
        self.max_straight_line_detour_km = max_straight_line_detour_km
        self.dwell_times = dwell_times or DwellTimes()
        self.routing_soft_budget = routing_soft_budget
        self.routing_hard_budget = routing_hard_budget
        self.max_reasonable_detour_minutes = max_reasonable_detour_minutes
        self.corridor_km = corridor_km
        self.endpoint_radius_km = endpoint_radius_km
        self.max_transit_node_distance_m = max_transit_node_distance_m
        self.max_hubs_per_category = max_hubs_per_category
        self.departure_time_bucket_minutes = max(1, departure_time_bucket_minutes)
        self.route_cache = RouteCache(route_cache_max_entries, route_cache_ttl_seconds)
        self.routing_concurrency = max(1, routing_concurrency)

    def _route_cache_key(self, start: Coordinate, end: Coordinate, departure: datetime) -> tuple[float, ...]:
        coordinate_key: tuple[float, ...] = (
            round(start.latitude, 6), round(start.longitude, 6),
            round(end.latitude, 6), round(end.longitude, 6),
        )
        if not self.provider.supports_departure_time_routing:
            return coordinate_key
        bucket = int(departure.timestamp() // (60 * self.departure_time_bucket_minutes))
        return coordinate_key + (float(bucket),)

    async def prepare_discovery_context(
        self, origin: Coordinate, destination: Coordinate, departure: datetime | None = None,
    ) -> tuple[DiscoverySearchContext, int, float]:
        """Route once before discovery and seed the optimizer cache for reuse."""
        effective = departure or datetime.now(SINGAPORE_TZ)
        key = self._route_cache_key(origin, destination, effective)
        baseline = self.route_cache.get(key)
        calls = 0
        latency_ms = 0.0
        if baseline is None:
            started = time.perf_counter()
            baseline = await self.provider.route_public_transport(origin, destination, effective)
            latency_ms = (time.perf_counter() - started) * 1000
            calls = 1
            self.route_cache.put(key, baseline)
        geometry = baseline_geometry(baseline, origin, destination)
        center = geometry[len(geometry) // 2] if geometry else Coordinate(
            (origin.latitude + destination.latitude) / 2,
            (origin.longitude + destination.longitude) / 2,
        )
        return DiscoverySearchContext(
            center=center, route_geometry=geometry, origin=origin, destination=destination,
        ), calls, round(latency_ms, 2)

    async def optimize(
        self,
        origin: Coordinate,
        destination: Coordinate,
        errands: list[str],
        departure: datetime | None = None,
        preferences: OptimizationPreferences | None = None,
        routing_call_offset: int = 0,
        fallbacks: tuple[CandidateFallback, ...] = (),
        extra_hubs: tuple[Hub, ...] = (),
    ) -> tuple[
        RouteResult,
        dict[str, ScoredCandidate],
        dict[str, float | int | bool | str | None],
        tuple[ScoredCandidate, ...],
    ]:
        """Generate candidates, fit them to the routing budget, price each one,
        choose what to offer, and report what else was compared."""
        started = time.perf_counter()
        prefs = preferences or OptimizationPreferences()
        session = _RoutingSession(self, departure, routing_call_offset)
        categories = normalize_categories(errands)

        baseline = await session.route(origin, destination, session.effective_start)
        pipeline, fallback_pipelines, options = await self._generate(
            categories, origin, destination, baseline, prefs, fallbacks, extra_hubs,
        )
        pruned = self._fit_to_budget(options, routing_call_offset)

        semaphore = asyncio.Semaphore(self.routing_concurrency)

        async def price(option: CandidateOption, stop_order: tuple[Hub, ...]) -> ScoredCandidate | None:
            async with semaphore:
                return await self._price(session, option, stop_order, origin, destination, baseline, prefs)

        jobs = [
            (option, tuple(stop_order))
            for option in pruned
            for stop_order in (permutations(option.stops) if len(option.stops) > 1 else (option.stops,))
        ]
        results = await asyncio.gather(*(price(option, order) for option, order in jobs))
        evaluated = [result for result in results if result is not None]

        recommendations, outcome = self._choose(evaluated, prefs, session.closed_errands())
        considered = _compared_but_not_offered(evaluated, recommendations)

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        diagnostics = self._diagnostics(
            session, pipeline, fallback_pipelines, pruned, evaluated, outcome, latency_ms,
        )
        logger.info(
            "optimization_complete generated_candidates=%s pruned_candidates=%s "
            "evaluated_candidates=%s routing_calls=%s cache_hits=%s "
            "provider_latency_ms=%s latency_ms=%s hard_budget_reached=%s",
            pipeline.hub_coverage_candidate_count,
            len(pruned),
            len(evaluated),
            session.routing_calls,
            session.cache_hits,
            round(session.provider_latency_ms, 2),
            latency_ms,
            session.hard_budget_reached,
        )
        return baseline, recommendations, diagnostics, considered

    async def _generate(
        self,
        categories: tuple[str, ...],
        origin: Coordinate,
        destination: Coordinate,
        baseline: RouteResult,
        prefs: OptimizationPreferences,
        fallbacks: tuple[CandidateFallback, ...],
        extra_hubs: tuple[Hub, ...],
    ) -> tuple[CandidatePipelineResult, list[CandidatePipelineResult], list[CandidateOption]]:
        """Candidates for the request itself, then one or two per fallback
        (a substitute kind of shop, or part of the request)."""
        # Candidate selection is CPU and SQLite work; run off the event loop
        # so one plan does not stall every other request (and /health).
        pipeline = await asyncio.to_thread(
            staged_candidate_pipeline,
            self.repository,
            categories,
            origin,
            destination,
            baseline,
            self.max_candidates if not fallbacks else max(1, self.max_candidates - 2),
            self.max_straight_line_detour_km,
            self.corridor_km,
            self.endpoint_radius_km,
            self.max_transit_node_distance_m,
            self.max_hubs_per_category,
            prefs.exact_brands,
            prefs.exact_places,
            extra_hubs,
        )
        options = [replace(option, requested_categories=categories) for option in pipeline.candidates]
        fallback_pipelines = []
        for fallback in fallbacks:
            fallback_pipeline = await asyncio.to_thread(
                staged_candidate_pipeline,
                self.repository,
                fallback.categories,
                origin,
                destination,
                baseline,
                1,
                self.max_straight_line_detour_km,
                self.corridor_km,
                self.endpoint_radius_km,
                self.max_transit_node_distance_m,
                self.max_hubs_per_category,
                fallback.exact_brands,
                fallback.exact_places,
            )
            fallback_pipelines.append(fallback_pipeline)
            options.extend(
                replace(
                    option,
                    match_classification=fallback.match_classification,
                    requested_categories=fallback.requested_categories,
                    omitted_categories=fallback.omitted_categories,
                    substituted_categories=fallback.substituted_categories,
                )
                for option in fallback_pipeline.candidates
            )
        return pipeline, fallback_pipelines, options

    def _fit_to_budget(self, options: list[CandidateOption], routing_call_offset: int) -> list[CandidateOption]:
        """Keep options, in order, while their estimated routing calls fit:
        two for one stop, six for two stops routed in both orders."""
        remaining = max(0, self.routing_hard_budget - routing_call_offset - 1)
        kept = []
        for option in options:
            calls = 2 if len(option.stops) == 1 else 6
            if calls <= remaining:
                kept.append(option)
                remaining -= calls
        return kept

    async def _price(
        self,
        session: "_RoutingSession",
        option: CandidateOption,
        stop_order: tuple[Hub, ...],
        origin: Coordinate,
        destination: Coordinate,
        baseline: RouteResult,
        prefs: OptimizationPreferences,
    ) -> ScoredCandidate | None:
        """Route one option in one order and measure it against the direct trip."""
        current_departure = session.effective_start
        current_coordinate = origin
        segments: list[RouteResult] = []
        dwell_total = 0.0
        stop_arrivals: list[datetime | None] = []
        stop_dwells: list[float] = []
        # When the router cannot be asked for a departure time, the clock is
        # still advanced here so opening hours can be checked.
        clock = session.effective_start
        estimated_arrivals: list[datetime] = []
        try:
            for stop in stop_order:
                segment = await session.route(current_coordinate, stop.coordinate, current_departure)
                segments.append(segment)
                dwell = self.dwell_times.for_categories(option.categories_at(stop.id))
                dwell_total += dwell
                stop_dwells.append(dwell)
                arrival = None
                if session.time_aware:
                    arrival = segment.arrival_time or (
                        current_departure + timedelta(minutes=segment.duration_minutes)
                    )
                    current_departure = arrival + timedelta(minutes=dwell)
                stop_arrivals.append(arrival)
                clock = arrival or (clock + timedelta(minutes=segment.duration_minutes))
                estimated_arrivals.append(clock)
                clock = clock + timedelta(minutes=dwell)
                current_coordinate = stop.coordinate
            segments.append(await session.route(current_coordinate, destination, current_departure))
        except RoutingBudgetExceeded:
            session.note_unrouted(option)
            return None
        except ProviderNoRouteError:
            session.no_route_candidate_count += 1
            session.note_unrouted(option)
            return None
        except ProviderError:
            # One failed check must not sink the plan: skip this place and let
            # the others stand. Only the direct trip is vital.
            session.provider_error_candidate_count += 1
            session.note_unrouted(option)
            return None

        open_on_arrival, closed_errand = _open_on_arrival(option, stop_order, estimated_arrivals, stop_dwells)
        if closed_errand is not None:
            session.closed_candidate_count += 1
            if option.match_classification == "best_match":
                session.closed_full_errands.add(closed_errand)
            return None
        if option.match_classification == "best_match":
            session.full_priced = True

        total = combine_routes(segments, dwell_minutes=dwell_total, time_dependent=session.time_aware)
        detour = round(max(0.0, total.duration_minutes - baseline.duration_minutes), 2)
        extra_walking = round(max(0.0, total.walking_minutes - baseline.walking_minutes), 2)
        extra_walking_distance = round(max(0.0, total.walking_distance_m - baseline.walking_distance_m), 1)
        extra_transfers = max(0, total.transfers - baseline.transfers)
        travel_minutes = float(total.raw_metadata.get("travel_minutes", total.duration_minutes - dwell_total))
        extra_travel = round(max(0.0, travel_minutes - baseline.duration_minutes), 2)

        soft_exceeded, hard_exceeded = _limits_exceeded(
            prefs, extra_travel, extra_walking, extra_transfers,
            total.arrival_time or (session.effective_start + timedelta(minutes=total.duration_minutes)),
        )
        if hard_exceeded or soft_exceeded or detour > self.max_reasonable_detour_minutes:
            session.excessive_detour_candidate_count += 1

        missing_brands = _missing_preferred_brands(option, prefs)
        preferred_satisfied = not missing_brands
        preference_adjustment = 0.0
        if prefs.preferred_brands and preferred_satisfied:
            preference_adjustment += self.weights.preferred_brand_bonus
        if prefs.prefer_consolidated_stops and option.consolidated:
            preference_adjustment += self.weights.consolidated_stop_bonus
        weighted = ScoringWeights(
            detour=self.weights.detour * prefs.detour_weight_multiplier,
            walking=self.weights.walking * prefs.walking_weight_multiplier,
            transfer=self.weights.transfer * prefs.transfer_weight_multiplier,
            preferred_brand_bonus=self.weights.preferred_brand_bonus,
            consolidated_stop_bonus=self.weights.consolidated_stop_bonus,
            data_quality_bonus=self.weights.data_quality_bonus,
        )
        data_quality = round(
            sum(hub_data_quality(stop, open_on_arrival[index]) for index, stop in enumerate(stop_order))
            / len(stop_order),
            3,
        )
        classification = self._classify(
            option.match_classification, hard_exceeded, soft_exceeded, detour, prefs, preferred_satisfied,
        )
        return ScoredCandidate(
            option=option,
            ordered_stops=tuple(stop_order),
            total_route=total,
            incremental_detour_minutes=detour,
            incremental_walking_minutes=extra_walking,
            incremental_transfers=extra_transfers,
            overall_score=calculate_score(detour, extra_walking, extra_transfers, weighted, data_quality)
            - preference_adjustment,
            incremental_walking_distance_m=extra_walking_distance,
            routed_segment_count=len(segments),
            stop_arrivals=tuple(stop_arrivals),
            stop_dwell_minutes=tuple(stop_dwells),
            explanation=(
                f"{_relationship_explanation(option.stop_relationship)}. Adds {detour:.1f} minutes, "
                f"{extra_walking:.1f} walking minutes and "
                f"{extra_transfers} transfers. {QUALITY_NOTES.get(classification, '')}"
            ),
            match_classification=classification,
            data_quality_score=data_quality,
            hard_constraints_satisfied=not hard_exceeded,
            incremental_travel_minutes=extra_travel,
            missing_preferred_brands=missing_brands,
        )

    def _classify(
        self,
        classification: str,
        hard_exceeded: list[str],
        soft_exceeded: list[str],
        detour: float,
        prefs: OptimizationPreferences,
        preferred_satisfied: bool,
    ) -> str:
        """What kind of answer a full match is. Fallbacks keep their own kind."""
        if classification != "best_match":
            return classification
        if hard_exceeded:
            return "exceeds_limit"
        if soft_exceeded:
            return "closest_exact"
        if detour > self.max_reasonable_detour_minutes:
            return "best_available"
        if prefs.preferred_brands:
            return "exact_match" if preferred_satisfied else "without_preferred_brand"
        return classification

    def _choose(
        self,
        evaluated: list[ScoredCandidate],
        prefs: OptimizationPreferences,
        closed_errands: frozenset[str] = frozenset(),
    ) -> tuple[dict[str, ScoredCandidate], str]:
        """The offered options: the best full matches, then fallbacks that earn
        a place, each with its sentence. Also the outcome of the search."""
        full = [item for item in evaluated if item.option.match_classification == "best_match"]
        accepted_full = [item for item in full if item.hard_constraints_satisfied]
        fallback_evaluated = [item for item in evaluated if item.option.match_classification != "best_match"]
        primary_pool = accepted_full or full or fallback_evaluated
        recommendations = rank_recommendations(primary_pool) if primary_pool else {}
        best = recommendations.get("best_overall")

        seen_stops = {tuple(stop.id for stop in item.ordered_stops) for item in recommendations.values()}
        for item in sorted(fallback_evaluated, key=lambda candidate: (candidate.overall_score, candidate.incremental_detour_minutes)):
            signature = tuple(stop.id for stop in item.ordered_stops)
            if signature in seen_stops:
                continue
            if accepted_full and best is not None and not _fallback_earns_a_place(item, best):
                continue
            if item.match_classification == "substitute":
                key = "substitute"
            elif item.match_classification == "partial_option":
                key = "partial_" + "_".join(item.option.required_categories)
            else:
                key = f"alternative_{len(recommendations)}"
            if key not in recommendations:
                recommendations[key] = item
                seen_stops.add(signature)
            if len(recommendations) >= 5:
                break

        explained = {
            key: replace(
                item,
                why_this_wins=(
                    explain_best(item, primary_pool, prefs, closed_errands)
                    if key == "best_overall"
                    else explain_alternative(key, item, best, prefs)
                ),
            )
            for key, item in recommendations.items()
        }

        if accepted_full:
            outcome = "best_available" if all(item.match_classification == "best_available" for item in accepted_full) else "ok"
        elif full:
            outcome = "closest_option"
        elif fallback_evaluated:
            outcome = "partial_or_substitute"
        else:
            outcome = "no_practical_match"
        return explained, outcome

    def _diagnostics(
        self,
        session: "_RoutingSession",
        pipeline: CandidatePipelineResult,
        fallback_pipelines: list[CandidatePipelineResult],
        pruned: list[CandidateOption],
        evaluated: list[ScoredCandidate],
        outcome: str,
        latency_ms: float,
    ) -> dict[str, float | int | bool | str | None]:
        time_aware = session.time_aware
        return {
            "generated_candidate_count": pipeline.hub_coverage_candidate_count
            + sum(item.hub_coverage_candidate_count for item in fallback_pipelines),
            "pruned_candidate_count": len(pruned),
            "evaluated_candidate_count": len(evaluated),
            "routing_call_count": session.routing_calls,
            "cache_hit_count": session.cache_hits,
            "provider_latency_ms": round(session.provider_latency_ms, 2),
            "optimization_latency_ms": latency_ms,
            "routing_soft_budget": self.routing_soft_budget,
            "routing_hard_budget": self.routing_hard_budget,
            "soft_budget_exceeded": session.soft_budget_warned,
            "hard_budget_reached": (
                session.hard_budget_reached
                or session.routing_calls + session.routing_call_offset >= self.routing_hard_budget
            ),
            "no_route_candidate_count": session.no_route_candidate_count,
            "provider_error_candidate_count": session.provider_error_candidate_count,
            "closed_candidate_count": session.closed_candidate_count,
            "time_aware_dwell_applied": time_aware,
            "departure_time_routing_verified": time_aware,
            "time_dependency_limitation": (
                None
                if time_aware
                else (
                    "Dwell is counted, but onward segments are not advanced because "
                    "live OneMap departure-time behaviour has not been verified."
                )
            ),
            "raw_poi_count": pipeline.raw_poi_count,
            "category_match_hub_count": pipeline.category_match_hub_count,
            "corridor_hub_count": pipeline.corridor_hub_count,
            "transit_proximity_hub_count": pipeline.transit_proximity_hub_count,
            "hub_coverage_candidate_count": pipeline.hub_coverage_candidate_count,
            "approximate_detour_candidate_count": pipeline.approximate_detour_candidate_count,
            "routing_budget_candidate_count": len(pruned),
            "baseline_geometry_point_count": pipeline.baseline_geometry_point_count,
            "excessive_detour_candidate_count": session.excessive_detour_candidate_count,
            "near_miss_candidate_count": len(pipeline.near_misses),
            "outcome": outcome,
            "routing_concurrency": self.routing_concurrency,
        }


QUALITY_NOTES = {
    "closest_exact": "It is slightly beyond the preference you gave us.",
    "best_available": "It adds more time than our usual comfortable range, but it is the least disruptive full match.",
    "without_preferred_brand": "It does not have the brand you prefer.",
    "substitute": "It uses a similar kind of shop instead of the one you asked for.",
    "partial_option": "It fits one useful part of the request into this journey.",
    "exceeds_limit": "It is the closest option we found, but it exceeds a limit you marked as strict.",
}


class _RoutingSession:
    """One optimisation's routing: the budget, the shared cache, de-duplicated
    in-flight calls, and the counters the diagnostics report."""

    def __init__(self, optimizer: Optimizer, departure: datetime | None, routing_call_offset: int):
        self.optimizer = optimizer
        self.departure = departure
        self.routing_call_offset = routing_call_offset
        self.time_aware = optimizer.provider.supports_departure_time_routing
        self.effective_start = departure or datetime.now(SINGAPORE_TZ)
        self.in_flight: dict[tuple[float, ...], asyncio.Task[RouteResult]] = {}
        self.routing_calls = 0
        self.cache_hits = 0
        self.provider_latency_ms = 0.0
        self.soft_budget_warned = False
        self.hard_budget_reached = False
        self.no_route_candidate_count = 0
        self.provider_error_candidate_count = 0
        self.closed_candidate_count = 0
        self.excessive_detour_candidate_count = 0
        # Errands that shut every full match that was otherwise routable, so a
        # fallback can say why it is a fallback.
        self.closed_full_errands: set[str] = set()
        self.full_priced = False
        self.full_unrouted = False

    def note_unrouted(self, option: CandidateOption) -> None:
        if option.match_classification == "best_match":
            self.full_unrouted = True

    def closed_errands(self) -> frozenset[str]:
        """Errands closed at every full match, when closure is the only reason
        none survived. Empty when a full match was priced or failed to route:
        then "nothing is open" would be a guess."""
        if self.full_priced or self.full_unrouted:
            return frozenset()
        return frozenset(self.closed_full_errands)

    async def route(self, start: Coordinate, end: Coordinate, effective_departure: datetime) -> RouteResult:
        optimizer = self.optimizer
        key = optimizer._route_cache_key(start, end, effective_departure)
        cached = optimizer.route_cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        existing_task = self.in_flight.get(key)
        if existing_task is not None:
            self.cache_hits += 1
            return await existing_task
        if self.routing_calls + self.routing_call_offset >= optimizer.routing_hard_budget:
            self.hard_budget_reached = True
            raise RoutingBudgetExceeded(f"Routing hard budget of {optimizer.routing_hard_budget} calls reached")
        self.routing_calls += 1
        if self.routing_calls + self.routing_call_offset > optimizer.routing_soft_budget and not self.soft_budget_warned:
            self.soft_budget_warned = True
            logger.warning(
                "routing_soft_budget_exceeded calls=%s soft_budget=%s hard_budget=%s",
                self.routing_calls + self.routing_call_offset,
                optimizer.routing_soft_budget,
                optimizer.routing_hard_budget,
            )

        async def call_provider() -> RouteResult:
            call_started = time.perf_counter()
            try:
                return await optimizer.provider.route_public_transport(
                    start, end, effective_departure if self.time_aware else self.departure,
                )
            finally:
                self.provider_latency_ms += (time.perf_counter() - call_started) * 1000

        task = asyncio.create_task(call_provider())
        self.in_flight[key] = task
        try:
            result = await task
            optimizer.route_cache.put(key, result)
            return result
        finally:
            self.in_flight.pop(key, None)


def _open_on_arrival(
    option: CandidateOption,
    stop_order: tuple[Hub, ...],
    arrivals: list[datetime],
    dwells: list[float],
) -> tuple[list[bool], str | None]:
    """Per stop, whether a matching shop is listed as open when you get there,
    and the first errand for which every matching shop is listed as shut - a
    closed place is not an answer however close it is."""
    open_flags: list[bool] = []
    for index, stop in enumerate(stop_order):
        stop_open = False
        for category in option.categories_at(stop.id):
            statuses = [
                check_hours(store.opening_hours or stop.opening_hours, arrivals[index], dwells[index])
                for store in stop.stores
                if category in store.all_categories
            ]
            if statuses and all(status == "closed" for status in statuses):
                return open_flags, category
            stop_open = stop_open or "open" in statuses
        open_flags.append(stop_open)
    return open_flags, None


def _limits_exceeded(
    prefs: OptimizationPreferences,
    extra_travel: float,
    extra_walking: float,
    extra_transfers: int,
    arrival: datetime,
) -> tuple[list[str], list[str]]:
    """Which of the person's limits an option breaks, soft and strict. A limit
    on the detour is a limit on travel: the time in the shop is the errand
    itself, the same wherever it is done."""
    soft: list[str] = []
    hard: list[str] = []
    if prefs.max_detour_minutes is not None and extra_travel > prefs.max_detour_minutes:
        (hard if prefs.max_detour_is_hard else soft).append("added time")
    if prefs.max_extra_walking_minutes is not None and extra_walking > prefs.max_extra_walking_minutes:
        (hard if prefs.max_extra_walking_is_hard else soft).append("walking")
    if prefs.max_additional_transfers is not None and extra_transfers > prefs.max_additional_transfers:
        (hard if prefs.max_additional_transfers_is_hard else soft).append("transfers")
    if prefs.arrival_by is not None:
        limit = prefs.arrival_by
        if limit.tzinfo is None:
            limit = limit.replace(tzinfo=SINGAPORE_TZ)
        if arrival > limit:
            hard.append("arrival time")
    return soft, hard


def _missing_preferred_brands(option: CandidateOption, prefs: OptimizationPreferences) -> tuple[str, ...]:
    return tuple(
        brand
        for category, brand in prefs.preferred_brands
        if category in option.required_categories
        and not any(
            category in option.categories_at(stop.id)
            and any(store.canonical_brand == brand and category in store.all_categories for store in stop.stores)
            for stop in option.stops
        )
    )


def _fallback_earns_a_place(item: ScoredCandidate, best: ScoredCandidate) -> bool:
    """Next to a full match, a one-errand option must save real travel and a
    substitute must get you there sooner; otherwise each reads as a cheaper
    answer than it is."""
    if item.match_classification == "partial_option":
        return best.incremental_travel_minutes - item.incremental_travel_minutes >= PARTIAL_OPTION_MIN_SAVING_MINUTES
    if item.match_classification == "substitute":
        return best.incremental_detour_minutes - item.incremental_detour_minutes >= PARTIAL_OPTION_MIN_SAVING_MINUTES
    return True


def _compared_but_not_offered(
    evaluated: list[ScoredCandidate],
    recommendations: dict[str, ScoredCandidate],
) -> tuple[ScoredCandidate, ...]:
    """Places that were routed but not offered, best first, so the map and the
    list can say what else was compared and what each would have cost. Keyed
    on the set of stops, because a two-stop option is routed in both orders."""
    offered = {frozenset(stop.id for stop in item.ordered_stops) for item in recommendations.values()}
    by_stop_set: dict[frozenset[int], ScoredCandidate] = {}
    for item in sorted(evaluated, key=lambda candidate: (candidate.overall_score, candidate.incremental_detour_minutes)):
        stop_set = frozenset(stop.id for stop in item.ordered_stops)
        if stop_set in offered or stop_set in by_stop_set:
            continue
        by_stop_set[stop_set] = item
    return tuple(by_stop_set.values())[:MAX_CONSIDERED_REPORTED]
