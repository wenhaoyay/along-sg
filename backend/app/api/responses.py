"""Turning domain results into API responses, and the request helpers the routes share."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.config import Settings
from app.db import HubRepository
from app.discovery_models import (
    DiscoveryConfidence,
    DiscoverySearchContext,
    DiscoverySource,
    EvidenceTier,
    ResolvedLocation,
    ResolvedPlace,
)
from app.domain import (
    Coordinate,
    GeocodeMatch,
    Hub,
    RouteLeg,
    RouteResult,
    ScoredCandidate,
    Store,
)
from app.presentation import (
    category_label,
    hub_display_name,
    hub_location_context,
    store_display_name,
)
from app.providers.base import (
    LocationNotFoundError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderNoRouteError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from app.providers.mock import haversine_km
from app.schemas import (
    CoordinateResponse,
    DetourBreakdownResponse,
    DiscoveryPlaceResponse,
    DisplayBusinessResponse,
    DwellAllowanceResponse,
    GeocodeResultResponse,
    LocationInput,
    NearMissResponse,
    NeedDiscoveryResponse,
    RecommendationResponse,
    RouteLegResponse,
    RouteResponse,
    StopResponse,
)
from app.services.candidates import decode_polyline, generate_near_misses
from app.services.discovery import LocationResolver, NeedResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx's INFO request line includes the full URL. Some upstream APIs require
# credentials in query parameters, so never allow that logger to emit at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)


async def resolve_location(resolver: LocationResolver, location: LocationInput) -> GeocodeMatch:
    if location.coordinate is not None:
        coordinate = Coordinate(location.coordinate.latitude, location.coordinate.longitude)
        return GeocodeMatch(
            label=f"{coordinate.latitude:.5f}, {coordinate.longitude:.5f}",
            coordinate=coordinate,
        )
    match = await resolver.require_confident(location.query or "")
    return GeocodeMatch(
        label=match.display_name, coordinate=match.coordinate, address=match.address,
        entity_type=match.entity_type,
    )


def resolved_location_response(match: ResolvedLocation) -> GeocodeResultResponse:
    return GeocodeResultResponse(
        # Preserve the long-standing Punggol mock autocomplete label while the
        # resolver itself retains the official canonical station name.
        label="Punggol MRT" if match.display_name == "Punggol MRT Station" else match.display_name,
        coordinate=CoordinateResponse(latitude=match.coordinate.latitude, longitude=match.coordinate.longitude),
        address=match.address, entity_type=match.entity_type,
        confirmed=match.confidence not in {DiscoveryConfidence.AMBIGUOUS, DiscoveryConfidence.UNRESOLVED},
        confidence=match.confidence.value, subtitle=match.subtitle,
    )


def need_discovery_response(result) -> NeedDiscoveryResponse:
    return NeedDiscoveryResponse(
        query=result.original_query, semantic_type=result.semantic_type.value,
        canonical_concept=result.canonical_concept, category=result.category,
        confidence=result.confidence.value, related_terms=list(result.related_terms),
        places=[DiscoveryPlaceResponse(
            display_name=place.display_name,
            coordinate=CoordinateResponse(latitude=place.coordinate.latitude, longitude=place.coordinate.longitude),
            address=place.address, mall_or_hub=place.mall_or_hub, category=place.category,
            confidence=place.confidence.value, evidence=list(place.evidence),
            evidence_tier=place.evidence_tier.value, suitability=place.suitability,
            provenance=[item.value for item in place.provenance],
        ) for place in result.places],
        live_fallback_used=result.live_fallback_used,
        live_provider_failed=result.live_provider_failed, clarification=result.clarification,
        discovery_calls=result.discovery_calls, cache_hits=result.cache_hits, latency_ms=result.latency_ms,
        open_need=result.open_need, provider_calls=result.provider_calls,
        provider_latency_ms=result.provider_latency_ms,
        web_fallback_used=result.web_fallback_used, grounding_calls=result.grounding_calls,
        warnings=list(result.warnings),
    )


async def discovery_hubs_for_intent(
    resolver: NeedResolver, intent, confirmed_places,
    context: DiscoverySearchContext | None = None,
) -> tuple[Hub, ...]:
    places: list[tuple[ResolvedPlace, str]] = []
    for errand in intent.required_errands + intent.optional_errands:
        if not errand.discovery_concept:
            continue
        resolved = await resolver.resolve(
            errand.discovery_concept, allow_live=True, context=context,
            open_need=errand.open_need,
        )
        places.extend(
            (place, errand.category) for place in resolved.places
            if place.evidence_tier in {EvidenceTier.VERIFIED, EvidenceTier.STRONG, EvidenceTier.SUPPORTED}
        )
    for item in confirmed_places:
        places.append((ResolvedPlace(
            display_name=item.display_name,
            coordinate=Coordinate(item.coordinate.latitude, item.coordinate.longitude),
            address=item.address, category=item.category,
            source=DiscoverySource.LOCAL_CATALOG, confidence=DiscoveryConfidence.EXACT,
        ), item.category))
    hubs: list[Hub] = []
    for place, category in places[:20]:
        group_name = place.mall_or_hub or place.display_name
        existing_index = next((index for index, hub in enumerate(hubs) if (
            compact_hub_name(hub.name) == compact_hub_name(group_name)
            and haversine_km(hub.coordinate, place.coordinate) <= 0.2
        )), None)
        store = Store(name=place.display_name, category=category, categories=(category,), source=place.source.value)
        if existing_index is not None:
            current = hubs[existing_index]
            if not any(item.category == category and item.name == store.name for item in current.stores):
                hubs[existing_index] = Hub(
                    id=current.id, name=current.name, coordinate=current.coordinate,
                    stores=(*current.stores, store), semantic_type="mall" if place.mall_or_hub else "transport_hub",
                    source=current.source, address=current.address or place.address,
                )
            continue
        hubs.append(Hub(
            id=-(len(hubs) + 1), name=group_name, coordinate=place.coordinate,
            stores=(store,), semantic_type="mall" if place.mall_or_hub else "standalone",
            source=place.source.value, address=place.address,
        ))
    return tuple(hubs)


def compact_hub_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def discovery_context(origin, destination) -> DiscoverySearchContext | None:
    if not origin or not destination:
        return None
    start = Coordinate(origin.coordinate.latitude, origin.coordinate.longitude)
    end = Coordinate(destination.coordinate.latitude, destination.coordinate.longitude)
    return DiscoverySearchContext(
        center=Coordinate((start.latitude + end.latitude) / 2, (start.longitude + end.longitude) / 2),
        route_geometry=(start, end), origin=start, destination=end,
    )


def geocode_response(match: GeocodeMatch) -> GeocodeResultResponse:
    return GeocodeResultResponse(
        label=match.label,
        coordinate=CoordinateResponse(
            latitude=match.coordinate.latitude,
            longitude=match.coordinate.longitude,
        ),
        postal_code=match.postal_code,
        address=match.address,
        entity_type=match.entity_type,
    )


def leg_response(leg: RouteLeg) -> RouteLegResponse:
    return RouteLegResponse(
        mode=leg.mode,
        duration_minutes=leg.duration_minutes,
        distance_m=leg.distance_m,
        from_name=leg.from_name,
        to_name=leg.to_name,
        departure_time=leg.departure_time,
        arrival_time=leg.arrival_time,
        geometry_format=leg.geometry_format,
        route_short_name=leg.route_short_name,
        route_long_name=leg.route_long_name,
        agency=leg.agency,
        stop_count=leg.stop_count,
        from_stop_code=leg.from_stop_code,
        to_stop_code=leg.to_stop_code,
        segment_index=leg.segment_index,
    )


def route_response(route: RouteResult) -> RouteResponse:
    return RouteResponse(
        duration_minutes=route.duration_minutes,
        walking_minutes=route.walking_minutes,
        walking_distance_m=route.walking_distance_m,
        transfers=route.transfers,
        provider=route.provider,
        legs=[
            leg_response(leg) for leg in route.legs
        ],
        departure_time=route.departure_time,
        arrival_time=route.arrival_time,
        dwell_minutes=route.dwell_minutes,
        time_dependent=route.time_dependent,
        geometry=route_geometry_response(route),
    )


def route_geometry_response(route: RouteResult) -> list[CoordinateResponse]:
    points: list[Coordinate] = []
    for leg in route.legs:
        if leg.geometry and leg.geometry_format in {None, "encoded_polyline"}:
            points.extend(decode_polyline(leg.geometry))
    return [CoordinateResponse(latitude=point.latitude, longitude=point.longitude) for point in points]


def recommendation_response(
    label: str,
    candidate: ScoredCandidate,
    categories: tuple[str, ...],
    dwell_times,
    offered: bool = True,
) -> RecommendationResponse:
    stops = []
    matched_categories = candidate.option.required_categories or categories
    from app.services.opening_hours import check_hours
    for stop_index, hub in enumerate(candidate.ordered_stops):
        arrival = candidate.stop_arrivals[stop_index] if stop_index < len(candidate.stop_arrivals) else None
        dwell = candidate.stop_dwell_minutes[stop_index] if stop_index < len(candidate.stop_dwell_minutes) else 0
        matching_stores = [
            store
            for store in hub.stores
            if set(store.all_categories) & set(matched_categories)
        ]
        matching = [
            f"{store_display_name(store)} · {next((item for item in store.all_categories if item in matched_categories), store.category)}"
            for store in matching_stores
        ]
        display_name = hub_display_name(hub)
        location = hub_location_context(hub)
        stops.append(
            StopResponse(
                name=display_name,
                arrival_time=arrival,
                display_name=display_name,
                coordinate=CoordinateResponse(
                    latitude=hub.coordinate.latitude,
                    longitude=hub.coordinate.longitude,
                ),
                matching_outlets=matching,
                businesses=[DisplayBusinessResponse(
                    display_name=store_display_name(store),
                    canonical_brand=store.canonical_brand,
                    category_labels=[category_label(item) for item in store.all_categories if item in matched_categories],
                    location_context=location.context,
                    opening_status=check_hours(store.opening_hours, arrival, dwell),
                    logo_url=store.logo_url,
                ) for store in matching_stores],
                semantic_type=hub.semantic_type,
                location_context=location.context,
                context_kind=location.kind,
                location_quality=location.quality,
                navigation_ready=location.navigation_ready,
            )
        )
    route = candidate.total_route
    allowances = [
        DwellAllowanceResponse(label=f"Estimated {category_label(category).lower()} stop", minutes=float(getattr(dwell_times, category, 0.0)))
        for category in matched_categories if float(getattr(dwell_times, category, 0.0)) > 0
    ]
    extra_transport = max(0.0, candidate.incremental_detour_minutes - route.dwell_minutes)
    return RecommendationResponse(
        offered=offered,
        legs=[leg_response(leg) for leg in route.legs],
        time_dependent=route.time_dependent,
        departure_time=route.departure_time if route.time_dependent else None,
        arrival_time=route.arrival_time if route.time_dependent else None,
        label=label,
        stops=stops,
        consolidated=candidate.option.consolidated,
        total_duration_minutes=route.duration_minutes,
        total_walking_minutes=route.walking_minutes,
        total_walking_distance_m=route.walking_distance_m,
        total_transfers=route.transfers,
        incremental_detour_minutes=candidate.incremental_detour_minutes,
        incremental_walking_minutes=candidate.incremental_walking_minutes,
        incremental_walking_distance_m=candidate.incremental_walking_distance_m,
        incremental_transfers=candidate.incremental_transfers,
        inconvenience_score=candidate.overall_score,
        dwell_minutes=route.dwell_minutes,
        routed_segment_count=candidate.routed_segment_count,
        stop_relationship=candidate.option.stop_relationship,
        explanation=candidate.explanation,
        why_this_wins={
            "Best Overall": (
                "Lowest combined added time, walking and transfer impact among the evaluated options."
            ),
            "Fastest": "Lowest added journey time among the evaluated options.",
            "Least Walking": "Lowest added walking among the evaluated options.",
        }.get(label, "A low-inconvenience option for this journey."),
        match_classification=candidate.match_classification,
        quality_label={
            "best_match": "Best option",
            "exact_match": "Exact match",
            "closest_exact": "Closest exact match",
            "best_available": "Best available",
            "easier_alternative": "Easier alternative",
            "partial_option": "Partial option",
            "exceeds_limit": "Closest option",
        }.get(candidate.match_classification, "Good match"),
        hard_constraints_satisfied=candidate.hard_constraints_satisfied,
        detour_breakdown=DetourBreakdownResponse(
            extra_transport_minutes=round(extra_transport, 2),
            dwell_minutes=round(route.dwell_minutes, 2),
            dwell_allowances=allowances,
            total_incremental_minutes=round(candidate.incremental_detour_minutes, 2),
            precision_note="Travel comes from the route check. Stop times are practical estimates, rounded for planning.",
        ),
        route_geometry=route_geometry_response(route),
    )


def near_miss_responses(
    repository: HubRepository,
    categories: tuple[str, ...],
    origin: Coordinate,
    destination: Coordinate,
) -> list[NearMissResponse]:
    return [
        NearMissResponse(
            requested_category=item.requested_category,
            substitute_category=item.substitute_category,
            stop_name=item.hub.name,
            approximate_straight_line_detour_km=item.approximate_detour_km,
            explanation=(
                "This nearby category alternative may be easier to fit. Its distance is an estimate until you choose it."
            ),
        )
        for item in generate_near_misses(
            repository, categories, origin, destination
        )
    ]


def provider_http_error(error: ProviderError) -> HTTPException:
    if isinstance(error, LocationNotFoundError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, ProviderRateLimitError):
        return HTTPException(status_code=503, detail=str(error), headers={"Retry-After": "2"})
    if isinstance(error, ProviderTimeoutError):
        return HTTPException(status_code=504, detail=str(error))
    if isinstance(error, ProviderNoRouteError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ProviderAuthenticationError):
        return HTTPException(status_code=502, detail=str(error))
    if isinstance(error, (ProviderUpstreamError, ProviderInvalidResponseError)):
        return HTTPException(status_code=502, detail=str(error))
    return HTTPException(status_code=502, detail=str(error))


def outcome_message(outcome: str, has_recommendations: bool) -> str | None:
    if not has_recommendations:
        return "We couldn't find a practical match for this journey. Try a broader category or remove a strict brand or time limit."
    return {
        "best_available": "No option fits our usual comfortable range. This is the least disruptive full match we found.",
        "closest_option": "The closest option is shown for comparison, but it goes beyond a limit you marked as strict.",
        "partial_or_substitute": "We couldn't fit everything comfortably, so here is the most useful alternative we found.",
    }.get(outcome)


def hidden_fields(settings: Settings) -> set[str] | None:
    """Response fields kept from the browser. Candidate counts, cache hits,
    token counts and LLM cost are for whoever runs the service: shown only
    with EXPOSE_DIAGNOSTICS=true (and in tests, which build Settings directly)."""
    return None if settings.expose_diagnostics else {"diagnostics"}
