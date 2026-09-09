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
from app.domain import CandidateFallback, Coordinate, Hub, OptimizationPreferences, RouteResult, ScoredCandidate
from app.presentation import hub_data_quality
from app.providers.base import MapProvider, ProviderNoRouteError
from app.services.candidates import baseline_geometry, normalize_categories, staged_candidate_pipeline
from app.discovery_models import DiscoverySearchContext


logger = logging.getLogger("journey_optimizer")
SINGAPORE_TZ = ZoneInfo("Asia/Singapore")


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
        legs=tuple(leg for route in routes for leg in route.legs),
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
        unique[key] = item
        seen.add(signature)
    return unique


# A different mall is a different answer only if the journey it produces differs
# by something a traveller would notice. Below these, it is noise.
INDISTINGUISHABLE_DETOUR_MINUTES = 2.0
INDISTINGUISHABLE_WALKING_METRES = 100.0


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
    ) -> tuple[RouteResult, dict[str, ScoredCandidate], dict[str, float | int | bool | str | None]]:
        started = time.perf_counter()
        routing_calls = 0
        cache_hits = 0
        provider_latency_ms = 0.0
        soft_budget_warned = False
        hard_budget_reached = False
        no_route_candidate_count = 0
        time_aware = self.provider.supports_departure_time_routing
        effective_start = departure or datetime.now(SINGAPORE_TZ)
        intent_preferences = preferences or OptimizationPreferences()
        in_flight: dict[tuple[float, ...], asyncio.Task[RouteResult]] = {}

        async def route(
            start: Coordinate,
            end: Coordinate,
            effective_departure: datetime,
        ) -> RouteResult:
            nonlocal routing_calls, cache_hits, provider_latency_ms
            nonlocal soft_budget_warned, hard_budget_reached
            key = self._route_cache_key(start, end, effective_departure)
            cached = self.route_cache.get(key)
            if cached is not None:
                cache_hits += 1
                return cached
            existing_task = in_flight.get(key)
            if existing_task is not None:
                cache_hits += 1
                return await existing_task
            if routing_calls + routing_call_offset >= self.routing_hard_budget:
                hard_budget_reached = True
                raise RoutingBudgetExceeded(
                    f"Routing hard budget of {self.routing_hard_budget} calls reached"
                )
            routing_calls += 1
            if (
                routing_calls + routing_call_offset > self.routing_soft_budget
                and not soft_budget_warned
            ):
                soft_budget_warned = True
                logger.warning(
                    "routing_soft_budget_exceeded calls=%s soft_budget=%s hard_budget=%s",
                    routing_calls + routing_call_offset,
                    self.routing_soft_budget,
                    self.routing_hard_budget,
                )
            async def call_provider() -> RouteResult:
                nonlocal provider_latency_ms
                call_started = time.perf_counter()
                try:
                    return await self.provider.route_public_transport(
                        start,
                        end,
                        effective_departure if time_aware else departure,
                    )
                finally:
                    provider_latency_ms += (time.perf_counter() - call_started) * 1000

            task = asyncio.create_task(call_provider())
            in_flight[key] = task
            try:
                result = await task
                self.route_cache.put(key, result)
                return result
            finally:
                in_flight.pop(key, None)

        categories = normalize_categories(errands)
        baseline = await route(origin, destination, effective_start)
        main_candidate_limit = self.max_candidates if not fallbacks else max(1, self.max_candidates - 2)
        pipeline = staged_candidate_pipeline(
            self.repository,
            categories,
            origin,
            destination,
            baseline,
            main_candidate_limit,
            self.max_straight_line_detour_km,
            self.corridor_km,
            self.endpoint_radius_km,
            self.max_transit_node_distance_m,
            self.max_hubs_per_category,
            intent_preferences.exact_brands,
            intent_preferences.exact_places,
            extra_hubs,
        )
        requested_categories = categories
        main_options = [
            replace(option, requested_categories=requested_categories)
            for option in pipeline.candidates
        ]
        fallback_pipelines = []
        fallback_options = []
        for fallback in fallbacks:
            fallback_pipeline = staged_candidate_pipeline(
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
            fallback_options.extend(
                replace(
                    option,
                    match_classification=fallback.match_classification,
                    requested_categories=fallback.requested_categories,
                    omitted_categories=fallback.omitted_categories,
                    substituted_categories=fallback.substituted_categories,
                )
                for option in fallback_pipeline.candidates
            )
        route_budget_remaining = max(
            0, self.routing_hard_budget - routing_call_offset - 1
        )
        pruned = []
        for option in [*main_options, *fallback_options]:
            estimated_calls = 2 if len(option.stops) == 1 else 6
            if estimated_calls <= route_budget_remaining:
                pruned.append(option)
                route_budget_remaining -= estimated_calls
        evaluated: list[ScoredCandidate] = []
        excessive_detour_candidate_count = 0
        semaphore = asyncio.Semaphore(self.routing_concurrency)

        async def evaluate(option, stop_order) -> ScoredCandidate | None:
            nonlocal no_route_candidate_count, excessive_detour_candidate_count
            async with semaphore:
                current_departure = effective_start
                current_coordinate = origin
                segments: list[RouteResult] = []
                dwell_total = 0.0
                stop_arrivals = []
                stop_dwells = []
                try:
                    for stop in stop_order:
                        segment = await route(
                            current_coordinate, stop.coordinate, current_departure
                        )
                        segments.append(segment)
                        dwell = self.dwell_times.for_categories(
                            option.categories_at(stop.id)
                        )
                        dwell_total += dwell
                        stop_dwells.append(dwell)
                        arrival = None
                        if time_aware:
                            arrival = segment.arrival_time or (
                                current_departure
                                + timedelta(minutes=segment.duration_minutes)
                            )
                            current_departure = arrival + timedelta(minutes=dwell)
                        stop_arrivals.append(arrival)
                        current_coordinate = stop.coordinate
                    segments.append(
                        await route(
                            current_coordinate, destination, current_departure
                        )
                    )
                except RoutingBudgetExceeded:
                    return None
                except ProviderNoRouteError:
                    no_route_candidate_count += 1
                    return None

                total = combine_routes(
                    segments,
                    dwell_minutes=dwell_total,
                    time_dependent=time_aware,
                )
                detour = round(
                    max(0.0, total.duration_minutes - baseline.duration_minutes), 2
                )
                extra_walking = round(
                    max(0.0, total.walking_minutes - baseline.walking_minutes), 2
                )
                extra_walking_distance = round(
                    max(0.0, total.walking_distance_m - baseline.walking_distance_m), 1
                )
                extra_transfers = max(0, total.transfers - baseline.transfers)
                soft_exceeded: list[str] = []
                hard_exceeded: list[str] = []
                if intent_preferences.max_detour_minutes is not None and detour > intent_preferences.max_detour_minutes:
                    (hard_exceeded if intent_preferences.max_detour_is_hard else soft_exceeded).append("added time")
                if intent_preferences.max_extra_walking_minutes is not None and extra_walking > intent_preferences.max_extra_walking_minutes:
                    (hard_exceeded if intent_preferences.max_extra_walking_is_hard else soft_exceeded).append("walking")
                if intent_preferences.max_additional_transfers is not None and extra_transfers > intent_preferences.max_additional_transfers:
                    (hard_exceeded if intent_preferences.max_additional_transfers_is_hard else soft_exceeded).append("transfers")
                if intent_preferences.arrival_by is not None:
                    arrival = total.arrival_time or (
                        effective_start + timedelta(minutes=total.duration_minutes)
                    )
                    arrival_limit = intent_preferences.arrival_by
                    if arrival_limit.tzinfo is None:
                        arrival_limit = arrival_limit.replace(tzinfo=SINGAPORE_TZ)
                    if arrival > arrival_limit:
                        hard_exceeded.append("arrival time")
                if hard_exceeded or soft_exceeded or detour > self.max_reasonable_detour_minutes:
                    excessive_detour_candidate_count += 1
                relationship_text = _relationship_explanation(
                    option.stop_relationship
                )
                preferred_satisfied = all(
                    any(
                        category in option.categories_at(stop.id)
                        and any(
                            store.canonical_brand == brand
                            and category in store.all_categories
                            for store in stop.stores
                        )
                        for stop in option.stops
                    )
                    for category, brand in intent_preferences.preferred_brands
                    if category in option.required_categories
                )
                preference_adjustment = 0.0
                if intent_preferences.preferred_brands and preferred_satisfied:
                    preference_adjustment += self.weights.preferred_brand_bonus
                if intent_preferences.prefer_consolidated_stops and option.consolidated:
                    preference_adjustment += self.weights.consolidated_stop_bonus
                weighted = ScoringWeights(
                    detour=self.weights.detour * intent_preferences.detour_weight_multiplier,
                    walking=self.weights.walking * intent_preferences.walking_weight_multiplier,
                    transfer=self.weights.transfer * intent_preferences.transfer_weight_multiplier,
                    preferred_brand_bonus=self.weights.preferred_brand_bonus,
                    consolidated_stop_bonus=self.weights.consolidated_stop_bonus,
                    data_quality_bonus=self.weights.data_quality_bonus,
                )
                data_quality = round(
                    sum(hub_data_quality(stop) for stop in option.stops) / len(option.stops), 3
                )
                classification = option.match_classification
                if classification == "best_match":
                    if hard_exceeded:
                        classification = "exceeds_limit"
                    elif soft_exceeded:
                        classification = "closest_exact"
                    elif detour > self.max_reasonable_detour_minutes:
                        classification = "best_available"
                    elif intent_preferences.preferred_brands and preferred_satisfied:
                        classification = "exact_match"
                    elif intent_preferences.preferred_brands and not preferred_satisfied:
                        classification = "easier_alternative"
                quality_note = {
                    "closest_exact": "It is slightly beyond the preference you gave us.",
                    "best_available": "It adds more time than our usual comfortable range, but it is the least disruptive full match.",
                    "easier_alternative": "It relaxes a preference that you allowed us to substitute.",
                    "partial_option": "It fits one useful part of the request into this journey.",
                    "exceeds_limit": "It is the closest option we found, but it exceeds a limit you marked as strict.",
                }.get(classification, "")
                return ScoredCandidate(
                    option=option,
                    ordered_stops=tuple(stop_order),
                    total_route=total,
                    incremental_detour_minutes=detour,
                    incremental_walking_minutes=extra_walking,
                    incremental_transfers=extra_transfers,
                    overall_score=max(0.0, calculate_score(
                        detour, extra_walking, extra_transfers, weighted, data_quality,
                    ) - preference_adjustment),
                    incremental_walking_distance_m=extra_walking_distance,
                    routed_segment_count=len(segments),
                    stop_arrivals=tuple(stop_arrivals),
                    stop_dwell_minutes=tuple(stop_dwells),
                    explanation=(
                        f"{relationship_text}. Adds {detour:.1f} minutes, "
                        f"{extra_walking:.1f} walking minutes and "
                        f"{extra_transfers} transfers. {quality_note}"
                    ),
                    match_classification=classification,
                    data_quality_score=data_quality,
                    hard_constraints_satisfied=not hard_exceeded,
                )

        jobs = [
            (option, tuple(stop_order))
            for option in pruned
            for stop_order in (
                permutations(option.stops) if len(option.stops) > 1 else (option.stops,)
            )
        ]
        results = await asyncio.gather(
            *(evaluate(option, stop_order) for option, stop_order in jobs)
        )
        evaluated.extend(result for result in results if result is not None)

        full = [item for item in evaluated if item.option.match_classification == "best_match"]
        accepted_full = [item for item in full if item.hard_constraints_satisfied]
        fallback_evaluated = [item for item in evaluated if item.option.match_classification != "best_match"]
        primary_pool = accepted_full or full or fallback_evaluated
        recommendations = rank_recommendations(primary_pool) if primary_pool else {}
        seen_stops = {tuple(stop.id for stop in item.ordered_stops) for item in recommendations.values()}
        for item in sorted(fallback_evaluated, key=lambda candidate: (candidate.overall_score, candidate.incremental_detour_minutes)):
            signature = tuple(stop.id for stop in item.ordered_stops)
            if signature in seen_stops:
                continue
            if item.match_classification == "easier_alternative":
                key = "easier_alternative"
            elif item.match_classification == "partial_option":
                suffix = "_".join(item.option.required_categories)
                key = f"partial_{suffix}"
            else:
                key = f"alternative_{len(recommendations)}"
            if key not in recommendations:
                recommendations[key] = item
                seen_stops.add(signature)
            if len(recommendations) >= 5:
                break
        if accepted_full:
            outcome = "best_available" if all(item.match_classification == "best_available" for item in accepted_full) else "ok"
        elif full:
            outcome = "closest_option"
        elif fallback_evaluated:
            outcome = "partial_or_substitute"
        else:
            outcome = "no_practical_match"
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        diagnostics: dict[str, float | int | bool | str | None] = {
            "generated_candidate_count": pipeline.hub_coverage_candidate_count + sum(item.hub_coverage_candidate_count for item in fallback_pipelines),
            "pruned_candidate_count": len(pruned),
            "evaluated_candidate_count": len(evaluated),
            "routing_call_count": routing_calls,
            "cache_hit_count": cache_hits,
            "provider_latency_ms": round(provider_latency_ms, 2),
            "optimization_latency_ms": latency_ms,
            "routing_soft_budget": self.routing_soft_budget,
            "routing_hard_budget": self.routing_hard_budget,
            "soft_budget_exceeded": soft_budget_warned,
            "hard_budget_reached": (
                hard_budget_reached
                or routing_calls + routing_call_offset >= self.routing_hard_budget
            ),
            "no_route_candidate_count": no_route_candidate_count,
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
            "excessive_detour_candidate_count": excessive_detour_candidate_count,
            "near_miss_candidate_count": len(pipeline.near_misses),
            "outcome": outcome,
            "routing_concurrency": self.routing_concurrency,
        }
        logger.info(
            "optimization_complete generated_candidates=%s pruned_candidates=%s "
            "evaluated_candidates=%s routing_calls=%s cache_hits=%s "
            "provider_latency_ms=%s latency_ms=%s hard_budget_reached=%s",
            pipeline.hub_coverage_candidate_count,
            len(pruned),
            len(evaluated),
            routing_calls,
            cache_hits,
            round(provider_latency_ms, 2),
            latency_ms,
            hard_budget_reached,
        )
        return baseline, recommendations, diagnostics
