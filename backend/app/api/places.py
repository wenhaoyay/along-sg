"""Places: geocoding, live bus arrivals, need discovery and the catalog."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request

from app.bus_network import is_in_operation, operating_hours_text, stop_display_name
from app.config import Settings
from app.db import HubRepository
from app.domain import SINGAPORE_TZ
from app.presentation import safe_label
from app.providers.base import ProviderError
from app.providers.datamall import ATTRIBUTION as DATAMALL_ATTRIBUTION
from app.providers.datamall import (
    BusArrivalProvider,
    MockBusArrivalProvider,
)
from app.schemas import (
    ArrivalEstimateResponse,
    BusArrivalResponse,
    BusArrivalsResponse,
    CatalogCategoryResponse,
    CatalogSearchResultResponse,
    GeocodeResponse,
    NeedDiscoveryResponse,
)
from app.services.discovery import LocationResolver, NeedResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx's INFO request line includes the full URL. Some upstream APIs require
# credentials in query parameters, so never allow that logger to emit at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.api.responses import (
    need_discovery_response,
    provider_http_error,
    resolved_location_response,
)


def register(app: FastAPI, app_settings: Settings) -> None:
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
