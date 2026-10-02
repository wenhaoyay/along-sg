"""Journeys: the direct baseline and the optimised plans, from errands or a parsed intent."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request

from app.config import Settings
from app.providers.base import (
    MapProvider,
    ProviderError,
)
from app.schemas import (
    IntentOptimizeRequest,
    JourneyRequest,
    JourneyResponse,
    OptimizeRequest,
    OptimizeResponse,
)
from app.services.candidates import normalize_categories
from app.services.intent_optimizer import optimize_intent
from app.services.intent_parser import IntentParserService
from app.services.optimizer import Optimizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx's INFO request line includes the full URL. Some upstream APIs require
# credentials in query parameters, so never allow that logger to emit at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.api.responses import (
    discovery_hubs_for_intent,
    geocode_response,
    hidden_fields,
    near_miss_responses,
    outcome_message,
    provider_http_error,
    recommendation_response,
    resolve_location,
    route_response,
)


def register(app: FastAPI, app_settings: Settings) -> None:
    internal_fields = hidden_fields(app_settings)

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

    @app.post("/api/optimize", response_model=OptimizeResponse, response_model_exclude=internal_fields)
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

    @app.post("/api/optimize-intent", response_model=OptimizeResponse, response_model_exclude=internal_fields)
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
