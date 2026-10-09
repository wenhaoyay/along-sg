from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.analytics import AnalyticsRepository
from app.api import admin, intent, journeys, places

# Re-exported: tests and tools import these from app.main.
from app.api.responses import (  # noqa: F401
    discovery_hubs_for_intent,
    provider_http_error,
    resolve_location,
)
from app.config import Settings
from app.db import HubRepository
from app.providers.base import MapProvider
from app.providers.datamall import (
    BusArrivalProvider,
    LtaDataMallProvider,
    MockBusArrivalProvider,
)
from app.providers.llm import OpenAIIntentProvider
from app.providers.mock import MockOneMapProvider
from app.providers.onemap import OneMapProvider
from app.providers.place_search import GeoapifyPlaceSearchProvider, TomTomPlaceSearchProvider
from app.providers.semantic_expansion import OpenAISemanticExpansionProvider
from app.providers.web_search import TavilyWebDiscoveryProvider
from app.services.discovery import LocationResolver, NeedResolver
from app.services.intent_parser import IntentMetrics, IntentParserService
from app.services.optimizer import Optimizer

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
        title="Along API",
        version="0.9.0",
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

    for module in (places, journeys, intent, admin):
        module.register(app, app_settings)

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


app = create_app()
