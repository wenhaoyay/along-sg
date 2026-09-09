from __future__ import annotations

from datetime import datetime

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.analytics import AnalyticsRepository
from app.db import HubRepository
from app.domain import (
    SINGAPORE_TZ,
    Coordinate, GeocodeMatch, Hub, RouteLeg, RouteResult, ScoredCandidate, Store,
)
from app.discovery_models import (
    DiscoveryConfidence, DiscoverySearchContext, DiscoverySource, EvidenceTier,
    ResolvedLocation, ResolvedPlace,
)
from app.intent_models import (
    IntentMetricsSnapshot, IntentParseDiagnostics, IntentParseResponse, IntentStatus,
    JourneyConflict, JourneyMention,
)
from app.providers.base import (
    MapProvider,
    ProviderAuthenticationError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderNoRouteError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from app.providers.datamall import (
    ATTRIBUTION as DATAMALL_ATTRIBUTION,
    BusArrivalProvider,
    LtaDataMallProvider,
    MockBusArrivalProvider,
)
from app.bus_network import is_in_operation, operating_hours_text, stop_display_name
from app.providers.mock import MockOneMapProvider
from app.providers.onemap import OneMapProvider
from app.providers.llm import OpenAIIntentProvider
from app.providers.place_search import GeoapifyPlaceSearchProvider, TomTomPlaceSearchProvider
from app.providers.semantic_expansion import OpenAISemanticExpansionProvider
from app.providers.web_search import TavilyWebDiscoveryProvider
from app.schemas import (
    BusArrivalResponse,
    BusArrivalsResponse,
    ArrivalEstimateResponse,
    CoordinateResponse,
    AnalyticsEventRequest,
    AnalyticsEventResponse,
    AnalyticsReportResponse,
    GeocodeResponse,
    GeocodeResultResponse,
    JourneyRequest,
    JourneyResponse,
    IntentOptimizeRequest,
    IntentParseRequest,
    LocationInput,
    NearMissResponse,
    OptimizeRequest,
    OptimizeResponse,
    RecommendationResponse,
    RouteLegResponse,
    RouteResponse,
    StopResponse,
    DisplayBusinessResponse,
    DetourBreakdownResponse,
    DwellAllowanceResponse,
    CatalogCategoryResponse,
    CatalogSearchResultResponse,
    DiscoveryPlaceResponse,
    NeedDiscoveryResponse,
)
from app.services.candidates import decode_polyline, generate_near_misses, normalize_categories
from app.services.optimizer import Optimizer
from app.services.intent_optimizer import optimize_intent
from app.services.intent_parser import IntentMetrics, IntentParserService
from app.services.journey_references import extract_journey_references, errand_only_text
from app.services.discovery import LocationResolver, NeedResolver
from app.presentation import category_label, hub_display_name, hub_location_context, safe_label, store_display_name
from app.providers.mock import haversine_km
from app.services.open_needs import open_category


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx's INFO request line includes the full URL. Some upstream APIs require
# credentials in query parameters, so never allow that logger to emit at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)


def build_bus_arrival_provider(settings: Settings) -> BusArrivalProvider:
    """Mock unless a key is present and mock mode is off.

    Deliberately not "live whenever a key exists": switching a demo onto real
    quota as a side effect of setting an environment variable is the kind of
    surprise this project avoids. `DATAMALL_MOCK=false` is the explicit opt-in.
    """
    if settings.datamall_mock or not settings.lta_account_key:
        return MockBusArrivalProvider()
    return LtaDataMallProvider(
        settings.lta_account_key,
        timeout_seconds=settings.datamall_timeout_seconds,
    )


def build_provider(settings: Settings) -> MapProvider:
    if settings.onemap_mock:
        return MockOneMapProvider()
    return OneMapProvider(
        settings.onemap_base_url,
        settings.onemap_email,
        settings.onemap_password,
        settings.onemap_timeout_seconds,
        settings.token_refresh_margin_seconds,
        max_retries=settings.onemap_max_retries,
        retry_backoff_seconds=settings.onemap_retry_backoff_seconds,
        departure_time_routing_verified=(
            settings.onemap_departure_time_routing_verified
        ),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = HubRepository(app_settings.database_path)
        repository.initialize()
        analytics = AnalyticsRepository(
            app_settings.analytics_database_path,
            app_settings.analytics_retention_days,
        )
        analytics.initialize()
        provider = build_provider(app_settings)
        live_place_provider = (
            TomTomPlaceSearchProvider(
                app_settings.tomtom_api_key,
                app_settings.discovery_timeout_seconds,
                app_settings.discovery_cache_ttl_seconds,
                app_settings.discovery_hard_budget,
                app_settings.discovery_provider_max_retries,
            )
            if app_settings.discovery_live_enabled and app_settings.tomtom_api_key
            else None
        )
        secondary_place_provider = (
            GeoapifyPlaceSearchProvider(
                app_settings.geoapify_api_key,
                app_settings.discovery_timeout_seconds,
                app_settings.discovery_cache_ttl_seconds,
                app_settings.discovery_provider_max_retries,
            )
            if app_settings.discovery_live_enabled and app_settings.geoapify_api_key
            else None
        )
        web_provider = (
            TavilyWebDiscoveryProvider(app_settings.tavily_api_key, app_settings.discovery_timeout_seconds)
            if app_settings.discovery_web_enabled and app_settings.tavily_api_key else None
        )
        semantic_provider = (
            OpenAISemanticExpansionProvider(
                app_settings.openai_api_key, app_settings.openai_intent_model,
                app_settings.openai_base_url, app_settings.openai_timeout_seconds,
            )
            if app_settings.discovery_semantic_llm_enabled and app_settings.openai_api_key else None
        )
        llm_provider = (
            OpenAIIntentProvider(
                api_key=app_settings.openai_api_key,
                model=app_settings.openai_intent_model,
                base_url=app_settings.openai_base_url,
                timeout_seconds=app_settings.openai_timeout_seconds,
            )
            if app_settings.llm_intent_enabled and app_settings.openai_api_key
            else None
        )
        app.state.settings = app_settings
        app.state.repository = repository
        app.state.analytics = analytics
        app.state.provider = provider
        app.state.bus_arrival_provider = build_bus_arrival_provider(app_settings)
        app.state.location_resolver = LocationResolver(repository, provider)
        app.state.need_resolver = NeedResolver(
            repository, live_place_provider,
            track_gaps=app_settings.discovery_gap_telemetry_enabled,
            secondary_provider=secondary_place_provider,
            web_provider=web_provider,
            semantic_provider=semantic_provider,
            primary_calls_per_need=app_settings.discovery_primary_calls_per_need,
            secondary_calls_per_need=app_settings.discovery_secondary_calls_per_need,
            web_calls_per_need=app_settings.discovery_web_calls_per_need,
            grounding_candidate_limit=app_settings.discovery_grounding_candidate_limit,
        )
        app.state.live_place_provider = live_place_provider
        app.state.secondary_place_provider = secondary_place_provider
        app.state.web_discovery_provider = web_provider
        app.state.semantic_expansion_provider = semantic_provider
        app.state.intent_metrics = IntentMetrics()
        app.state.intent_parser = IntentParserService(
            repository, llm_provider, app.state.intent_metrics
        )
        app.state.optimizer = Optimizer(
            provider,
            repository,
            app_settings.scoring,
            app_settings.max_candidates,
            app_settings.max_straight_line_detour_km,
            app_settings.dwell_times,
            app_settings.routing_soft_budget,
            app_settings.routing_hard_budget,
            app_settings.max_reasonable_detour_minutes,
            app_settings.candidate_corridor_km,
            app_settings.candidate_endpoint_radius_km,
            app_settings.candidate_max_transit_node_distance_m,
            app_settings.candidate_max_hubs_per_category,
            app_settings.route_cache_max_entries,
            app_settings.route_cache_ttl_seconds,
            app_settings.route_cache_departure_bucket_minutes,
            app_settings.routing_concurrency,
        )
        yield
        await app.state.bus_arrival_provider.close()
        close = getattr(provider, "close", None)
        if close is not None:
            await close()
        if llm_provider is not None:
            await llm_provider.close()
        if live_place_provider is not None:
            await live_place_provider.close()
        if secondary_place_provider is not None:
            await secondary_place_provider.close()
        if web_provider is not None:
            await web_provider.close()
        if semantic_provider is not None:
            await semantic_provider.close()

    app = FastAPI(
        title="Singapore Journey-aware Errand Optimiser",
        version="0.7.4",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.get("/health")
    async def health() -> dict[str, str | bool]:
        return {"status": "ok", "onemap_mock": app_settings.onemap_mock}

    @app.get("/api/geocode", response_model=GeocodeResponse)
    async def geocode(request: Request, q: str = Query(min_length=2, max_length=160), limit: int = Query(default=6, ge=1, le=10)):
        resolver: LocationResolver = request.app.state.location_resolver
        try:
            matches = await resolver.resolve(q, limit=limit)
        except ProviderError as error:
            raise provider_http_error(error) from error
        return GeocodeResponse(
            query=q,
            results=[resolved_location_response(match) for match in matches],
            provider="along-discovery",
        )

    @app.get("/api/bus-arrivals", response_model=BusArrivalsResponse)
    async def bus_arrivals(
        request: Request,
        stop_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"),
        service: str | None = Query(default=None, max_length=8),
    ):
        """Live arrivals at one bus stop.

        Five digits exactly, because that is what a BusStopCode is - a rail
        leg's `NE17` is not a bus stop and must not reach DataMall as one.

        An empty `services` list is a normal answer, not an error: LTA returns
        no body at all when nothing is running, and a stop with nothing due
        looks identical. The client says "no live times" rather than inventing
        a reason, because telling the two apart needs each service's operating
        hours from the Bus Routes dataset, which this app does not hold yet.
        """
        provider: BusArrivalProvider = request.app.state.bus_arrival_provider
        try:
            arrivals = await provider.arrivals(stop_code, service)
        except ProviderError as error:
            raise provider_http_error(error) from error
        now = datetime.now(SINGAPORE_TZ)
        live = not isinstance(provider, MockBusArrivalProvider)
        # The static network, if it has been ingested. Its only job here is to
        # let an empty answer explain itself: "nothing due" and "stopped for the
        # night" look identical on the arrivals feed.
        repository: HubRepository = request.app.state.repository
        stop = repository.bus_stop(stop_code)
        in_operation: bool | None = None
        operating_hours: str | None = None
        if service:
            for row in repository.bus_routes_at_stop(stop_code):
                if row["service_no"] != service:
                    continue
                scheduled = is_in_operation(row, now)
                # A service can pass a stop in one direction only, so any
                # direction that is running means the service is running here.
                if scheduled:
                    in_operation, operating_hours = True, operating_hours_text(row, now)
                    break
                if in_operation is None:
                    in_operation = scheduled
                    operating_hours = operating_hours_text(row, now)
        return BusArrivalsResponse(
            stop_name=stop_display_name(stop) if stop else None,
            in_operation=in_operation,
            operating_hours=operating_hours,
            stop_code=stop_code,
            checked_at=now,
            source="lta_datamall" if live else "mock",
            attribution=DATAMALL_ATTRIBUTION if live else None,
            services=[
                BusArrivalResponse(
                    service_no=arrival.service_no,
                    operator=arrival.operator,
                    estimates=[
                        ArrivalEstimateResponse(
                            minutes=estimate.minutes_away(now),
                            arrival_time=estimate.arrival_time,
                            live=estimate.live,
                            load=estimate.load,
                            wheelchair_accessible=estimate.wheelchair_accessible,
                            vehicle_type=estimate.vehicle_type,
                        )
                        for estimate in arrival.estimates
                    ],
                )
                for arrival in arrivals
            ],
        )

    @app.get("/api/discovery/needs", response_model=NeedDiscoveryResponse)
    async def discover_need(
        request: Request,
        q: str = Query(min_length=2, max_length=100),
        limit: int = Query(default=10, ge=1, le=20),
        live: bool = Query(default=True),
    ):
        resolver: NeedResolver = request.app.state.need_resolver
        result = await resolver.resolve(q, limit=limit, allow_live=live)
        return need_discovery_response(result)

    @app.get("/api/catalog/categories", response_model=list[CatalogCategoryResponse])
    async def catalog_categories(request: Request):
        repository: HubRepository = request.app.state.repository
        return [CatalogCategoryResponse(**item) for item in repository.category_catalog_entries()]

    @app.get("/api/catalog/search", response_model=list[CatalogSearchResultResponse])
    async def catalog_search(
        request: Request,
        q: str = Query(default="", max_length=100),
        category: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=20, ge=1, le=50),
    ):
        repository: HubRepository = request.app.state.repository
        if category and category not in repository.category_catalog():
            raise HTTPException(status_code=422, detail="Unknown catalog category")
        results: list[CatalogSearchResultResponse] = []
        seen: set[tuple[str, str]] = set()
        for item in repository.search_catalog(q, category, limit):
            display_name = safe_label(item["display_name"], "Independent place")
            key = (item["kind"], display_name.casefold())
            if key in seen:
                continue
            seen.add(key)
            results.append(CatalogSearchResultResponse(**{
                **item,
                "display_name": display_name,
                "example_location": safe_label(item["example_location"]) if item["example_location"] else None,
            }))
        return results

    @app.post("/api/journey", response_model=JourneyResponse)
    async def journey(payload: JourneyRequest, request: Request):
        provider: MapProvider = request.app.state.provider
        try:
            origin = await resolve_location(request.app.state.location_resolver, payload.origin)
            destination = await resolve_location(request.app.state.location_resolver, payload.destination)
            route = await provider.route_public_transport(
                origin.coordinate,
                destination.coordinate,
                payload.departure,
            )
        except ProviderError as error:
            raise provider_http_error(error) from error
        return JourneyResponse(
            origin=geocode_response(origin),
            destination=geocode_response(destination),
            route=route_response(route),
        )

    @app.post("/api/optimize", response_model=OptimizeResponse)
    async def optimize(payload: OptimizeRequest, request: Request):
        provider: MapProvider = request.app.state.provider
        optimizer: Optimizer = request.app.state.optimizer
        try:
            origin = await resolve_location(request.app.state.location_resolver, payload.origin)
            destination = await resolve_location(request.app.state.location_resolver, payload.destination)
            baseline, recommendations, diagnostics, considered = await optimizer.optimize(
                origin.coordinate,
                destination.coordinate,
                payload.errands,
                payload.departure,
            )
        except ProviderError as error:
            raise provider_http_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        categories = normalize_categories(payload.errands)
        labels = {
            "best_overall": "Best Overall",
            "fastest": "Fastest",
            "least_walking": "Least Walking",
        }
        return OptimizeResponse(
            origin=geocode_response(origin),
            destination=geocode_response(destination),
            errands=list(categories),
            baseline=route_response(baseline),
            recommendations={
                **{
                    key: recommendation_response(labels.get(key, "Alternative"), candidate, categories, app_settings.dwell_times)
                    for key, candidate in recommendations.items()
                },
                # Routed, rejected, and selectable anyway. Keyed separately so
                # the client can tell what was volunteered from what was merely
                # compared without inspecting the flag on every entry.
                **{
                    f"compared_{index}": recommendation_response(
                        "Also compared", candidate, categories, app_settings.dwell_times,
                        offered=False,
                    )
                    for index, candidate in enumerate(considered)
                },
            },
            diagnostics=diagnostics,
            outcome=str(diagnostics["outcome"]),
            message=(
                outcome_message(str(diagnostics["outcome"]), bool(recommendations))
            ),
            near_misses=(
                near_miss_responses(
                    request.app.state.repository,
                    categories,
                    origin.coordinate,
                    destination.coordinate,
                )
                if not recommendations
                else []
            ),
        )

    @app.post("/api/intent/parse", response_model=IntentParseResponse)
    async def parse_intent(payload: IntentParseRequest, request: Request):
        parser: IntentParserService = request.app.state.intent_parser
        provider: MapProvider = request.app.state.provider
        references = extract_journey_references(payload.text)
        mentions: list[JourneyMention] = []
        conflicts: list[JourneyConflict] = []
        for reference in references:
            try:
                matches = await request.app.state.location_resolver.resolve(reference.text, limit=3)
            except ProviderError:
                matches = []
            match = matches[0] if matches and matches[0].confidence != DiscoveryConfidence.AMBIGUOUS else None
            mentions.append(JourneyMention(
                endpoint=reference.endpoint, text=reference.text,
                resolved_label=match.display_name if match else None,
                latitude=match.coordinate.latitude if match else None,
                longitude=match.coordinate.longitude if match else None,
            ))
            current = payload.origin if reference.endpoint == "origin" else payload.destination
            if current is not None:
                differs = match is None or haversine_km(
                    Coordinate(current.coordinate.latitude, current.coordinate.longitude),
                    match.coordinate,
                ) > 0.5
                if differs:
                    conflicts.append(JourneyConflict(
                        endpoint=reference.endpoint,
                        current_label=current.label,
                        mentioned_text=reference.text,
                        mentioned_label=match.display_name if match else None,
                        latitude=match.coordinate.latitude if match else None,
                        longitude=match.coordinate.longitude if match else None,
                        reason=(
                            f"Your {reference.endpoint} above is {current.label}, but your request "
                            f"mentions {match.display_name if match else reference.text}."
                        ),
                    ))
        errand_text = errand_only_text(payload.text, references)
        if not errand_text:
            return IntentParseResponse(
                status=IntentStatus.NEEDS_CLARIFICATION,
                unresolved_terms=[],
                clarification_question=(
                    "It looks like you're trying to change your destination. Update the To field instead."
                    if any(item.endpoint == "destination" for item in references)
                    else "I couldn't find an errand in that request. Try ‘KFC and bubble tea’, ‘buy toothpaste with minimal walking’, or ‘coffee if convenient’."
                ),
                diagnostics=IntentParseDiagnostics(clarification_required=True),
                journey_mentions=mentions,
                journey_conflicts=conflicts,
            )
        parsed = await parser.parse(errand_text, correction=payload.correction)
        resolver: NeedResolver = request.app.state.need_resolver
        open_needs = resolver.parse_open_needs(errand_text)
        parsed_count = len(parsed.intent.required_errands + parsed.intent.optional_errands) if parsed.intent else 0
        needs_open_discovery = parsed.status == IntentStatus.UNRESOLVED or len(open_needs) > parsed_count
        if needs_open_discovery and open_needs:
            from app.intent_models import IntentErrand, IntentV1, ParseMethod

            search_context = discovery_context(payload.origin, payload.destination)
            discoveries = [
                await resolver.resolve(
                    need.raw_text, allow_live=True, context=search_context, open_need=need,
                )
                for need in open_needs
            ]
            required: list[IntentErrand] = []
            optional: list[IntentErrand] = []
            unresolved_terms: list[str] = []
            for index, discovery in enumerate(discoveries):
                if not discovery.places or not discovery.open_need:
                    unresolved_terms.append(discovery.original_query)
                    continue
                errand = IntentErrand(
                    category=open_category(discovery.open_need.normalized_text, index),
                    required=not discovery.open_need.optional,
                    substitutes_allowed=discovery.open_need.substitution_allowed,
                    discovery_concept=discovery.canonical_concept or discovery.original_query,
                    open_need=discovery.open_need,
                    discovery_category=discovery.category,
                )
                (optional if discovery.open_need.optional else required).append(errand)
            if required or optional:
                partial_message = (
                    "Found options for the other errand, but couldn't reliably find "
                    + ", ".join(unresolved_terms) + ". You can continue with what was found or edit the missing item."
                    if unresolved_terms else None
                )
                parsed = IntentParseResponse(
                    status=IntentStatus.RESOLVED,
                    intent=IntentV1(
                        original_text=errand_text, required_errands=required,
                        optional_errands=optional, parse_method=ParseMethod.DETERMINISTIC,
                        confidence=min((0.9 if item.places else 0.7) for item in discoveries),
                    ),
                    unresolved_terms=unresolved_terms,
                    clarification_question=partial_message,
                    diagnostics=IntentParseDiagnostics(
                        parser_latency_ms=sum(item.latency_ms for item in discoveries),
                        fallback_used=True, clarification_required=bool(unresolved_terms),
                    ),
                )
            else:
                parsed = IntentParseResponse(
                    status=IntentStatus.NEEDS_CLARIFICATION,
                    unresolved_terms=[item.original_query for item in discoveries],
                    clarification_question=(
                        "We couldn't find a reliable place for "
                        + " and ".join(f"'{item.original_query}'" for item in discoveries)
                        + ". Try a broader category, edit the request, or retry current places."
                    ),
                    diagnostics=IntentParseDiagnostics(
                        parser_latency_ms=sum(item.latency_ms for item in discoveries),
                        fallback_used=True, clarification_required=True,
                    ),
                )
        question = parsed.clarification_question
        status = parsed.status
        if conflicts:
            status = IntentStatus.NEEDS_CLARIFICATION
            question = conflicts[0].reason
        elif references and any(item.resolved_label is None for item in mentions):
            status = IntentStatus.NEEDS_CLARIFICATION
            question = "I found a journey change, but could not resolve that Singapore location. Please update the From or To field directly."
        return parsed.model_copy(update={
            "status": status, "clarification_question": question,
            "journey_mentions": mentions, "journey_conflicts": conflicts,
        })

    @app.get("/api/intent/metrics", response_model=IntentMetricsSnapshot)
    async def intent_metrics(request: Request):
        metrics: IntentMetrics = request.app.state.intent_metrics
        return metrics.snapshot()

    @app.post("/api/optimize-intent", response_model=OptimizeResponse)
    async def optimize_with_intent(payload: IntentOptimizeRequest, request: Request):
        provider: MapProvider = request.app.state.provider
        optimizer: Optimizer = request.app.state.optimizer
        parser: IntentParserService = request.app.state.intent_parser
        canonical, unresolved = parser.validate_intent(payload.intent)
        if canonical is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Intent contains unresolved catalog terms.",
                    "unresolved_terms": unresolved,
                },
            )
        try:
            origin = await resolve_location(request.app.state.location_resolver, payload.origin)
            destination = await resolve_location(request.app.state.location_resolver, payload.destination)
            route_context, discovery_route_calls, discovery_route_latency_ms = (
                await optimizer.prepare_discovery_context(
                    origin.coordinate, destination.coordinate, payload.departure,
                )
            )
            extra_hubs = await discovery_hubs_for_intent(
                request.app.state.need_resolver, canonical, payload.confirmed_discovery_places,
                route_context,
            )
            baseline, recommendations, diagnostics, optimized_categories, considered = (
                await asyncio.wait_for(optimize_intent(
                    optimizer,
                    origin.coordinate,
                    destination.coordinate,
                    canonical,
                    payload.departure,
                    extra_hubs,
                    discovery_route_calls,
                ), timeout=app_settings.optimization_timeout_seconds)
            )
            diagnostics["route_corridor_discovery_calls"] = discovery_route_calls
            diagnostics["route_corridor_provider_latency_ms"] = discovery_route_latency_ms
        except ProviderError as error:
            raise provider_http_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except TimeoutError as error:
            raise HTTPException(
                status_code=504,
                detail="Optimization timed out before a bounded result was available.",
            ) from error

        if any(
            candidate.match_classification != "best_match"
            for candidate in recommendations.values()
        ):
            request.app.state.intent_metrics.near_miss_alternatives_selected += 1
        categories = tuple(optimized_categories)
        labels = {
            "best_overall": "Best Overall",
            "fastest": "Fastest",
            "least_walking": "Least Walking",
        }
        return OptimizeResponse(
            origin=geocode_response(origin),
            destination=geocode_response(destination),
            errands=list(categories),
            baseline=route_response(baseline),
            recommendations={
                **{
                    key: recommendation_response(labels.get(key, "Alternative"), candidate, categories, app_settings.dwell_times)
                    for key, candidate in recommendations.items()
                },
                # Routed, rejected, and selectable anyway. Keyed separately so
                # the client can tell what was volunteered from what was merely
                # compared without inspecting the flag on every entry.
                **{
                    f"compared_{index}": recommendation_response(
                        "Also compared", candidate, categories, app_settings.dwell_times,
                        offered=False,
                    )
                    for index, candidate in enumerate(considered)
                },
            },
            diagnostics=diagnostics,
            outcome=str(diagnostics["outcome"]),
            message=(
                outcome_message(str(diagnostics["outcome"]), bool(recommendations))
            ),
            intent=canonical,
            near_misses=(
                near_miss_responses(
                    request.app.state.repository,
                    tuple(
                        item.category
                        for item in canonical.required_errands
                        + canonical.optional_errands
                        if item.substitutes_allowed and not item.exact_brand
                    ),
                    origin.coordinate,
                    destination.coordinate,
                )
                if not recommendations
                else []
            ),
        )

    @app.post("/api/analytics/events", response_model=AnalyticsEventResponse)
    async def record_analytics(payload: AnalyticsEventRequest, request: Request):
        analytics: AnalyticsRepository = request.app.state.analytics
        return AnalyticsEventResponse(accepted=analytics.record(payload))

    @app.get("/api/admin/analytics", response_model=AnalyticsReportResponse)
    async def analytics_report(request: Request):
        expected = app_settings.beta_admin_token
        if not expected:
            raise HTTPException(status_code=404, detail="Not found")
        authorization = request.headers.get("authorization", "")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid admin token")
        analytics: AnalyticsRepository = request.app.state.analytics
        return analytics.report()

    @app.get("/api/admin/discovery-gaps")
    async def discovery_gap_report(request: Request):
        expected = app_settings.beta_admin_token
        if not expected or not app_settings.discovery_gap_telemetry_enabled:
            raise HTTPException(status_code=404, detail="Not found")
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid admin token")
        return request.app.state.need_resolver.metrics_snapshot()

    if app_settings.serve_frontend_dir is not None:
        if not app_settings.serve_frontend_dir.is_dir():
            raise RuntimeError(
                f"Configured frontend directory does not exist: {app_settings.serve_frontend_dir}"
            )
        app.mount(
            "/",
            StaticFiles(directory=app_settings.serve_frontend_dir, html=True),
            name="frontend",
        )

    return app


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


app = create_app()
