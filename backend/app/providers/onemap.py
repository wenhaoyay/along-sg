from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.domain import Coordinate, GeocodeMatch, RouteLeg, RouteResult
from app.providers.base import (
    MapProvider,
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderNoRouteError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)


SINGAPORE_TZ = ZoneInfo("Asia/Singapore")


class OneMapTokenManager:
    """Acquire and cache OneMap tokens exclusively in backend memory."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        email: str | None,
        password: str | None,
        refresh_margin_seconds: int = 300,
    ):
        self._client = client
        self._base_url = base_url
        self._email = email
        self._password = password
        self._refresh_margin_seconds = refresh_margin_seconds
        self._token: str | None = None
        self._expiry_epoch = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._is_valid():
            return self._token or ""
        async with self._lock:
            if not force_refresh and self._is_valid():
                return self._token or ""
            if not self._email or not self._password:
                raise ProviderAuthenticationError(
                    "OneMap credentials are unavailable; use mock mode or configure backend credentials"
                )
            try:
                response = await self._client.post(
                    f"{self._base_url}/api/auth/post/getToken",
                    json={"email": self._email, "password": self._password},
                )
            except httpx.TimeoutException as error:
                raise ProviderTimeoutError("OneMap authentication timed out") from error
            except httpx.RequestError as error:
                raise ProviderUpstreamError("OneMap authentication could not be reached") from error

            if response.status_code in {401, 403, 404}:
                raise ProviderAuthenticationError("OneMap authentication failed")
            if response.status_code == 429:
                raise ProviderRateLimitError("OneMap authentication was rate limited")
            if response.status_code >= 500:
                raise ProviderUpstreamError("OneMap authentication service failed")
            if response.status_code >= 400:
                raise ProviderAuthenticationError("OneMap rejected the authentication request")
            try:
                payload = response.json()
            except ValueError as error:
                raise ProviderInvalidResponseError(
                    "OneMap authentication returned invalid JSON"
                ) from error
            if not isinstance(payload, dict) or not payload.get("access_token"):
                raise ProviderInvalidResponseError(
                    "OneMap authentication returned no access token"
                )
            try:
                expiry = float(payload.get("expiry_timestamp", time.time() + 3600))
            except (TypeError, ValueError) as error:
                raise ProviderInvalidResponseError(
                    "OneMap authentication returned an invalid expiry"
                ) from error
            self._token = str(payload["access_token"])
            self._expiry_epoch = expiry
            return self._token

    def invalidate(self) -> None:
        self._expiry_epoch = 0.0

    def _is_valid(self) -> bool:
        return bool(
            self._token
            and time.time() < self._expiry_epoch - self._refresh_margin_seconds
        )


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: object) -> str | None:
    """Empty strings are how OneMap says "not applicable" on a walking leg."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip().replace(".", "", 1).isdigit():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (
                parsed.astimezone(SINGAPORE_TZ)
                if parsed.tzinfo
                else parsed.replace(tzinfo=SINGAPORE_TZ)
            )
        except ValueError:
            return None
    numeric = _number(value, -1)
    if numeric < 0:
        return None
    seconds = numeric / 1000.0 if numeric > 100_000_000_000 else numeric
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).astimezone(SINGAPORE_TZ)
    except (OverflowError, OSError, ValueError):
        return None


def _geometry(leg: dict[str, Any]) -> tuple[str | None, str | None]:
    geometry = leg.get("legGeometry", leg.get("geometry"))
    if isinstance(geometry, dict):
        points = geometry.get("points")
        if isinstance(points, str):
            return points, "encoded_polyline"
        if geometry.get("type") and geometry.get("coordinates") is not None:
            return json.dumps(geometry, separators=(",", ":")), "geojson"
    if isinstance(geometry, str):
        return geometry, "encoded_polyline"
    return None, None


class OneMapNormalizer:
    """The only component allowed to understand OneMap PT response field names."""

    def normalize_public_transport(self, payload: dict[str, Any]) -> RouteResult:
        if not isinstance(payload, dict):
            raise ProviderInvalidResponseError("OneMap PT response was not an object")
        error_message = str(payload.get("error", ""))
        if error_message:
            if "no route" in error_message.casefold() or "no path" in error_message.casefold():
                raise ProviderNoRouteError("OneMap found no public-transport route")
            raise ProviderInvalidResponseError("OneMap PT response contained an error")

        plan = payload.get("plan")
        schema_variant = "plan"
        if not isinstance(plan, dict) and isinstance(payload.get("data"), dict):
            plan = payload["data"].get("plan")
            schema_variant = "data.plan"
        if not isinstance(plan, dict):
            raise ProviderInvalidResponseError("OneMap PT response did not contain a route plan")
        itineraries = plan.get("itineraries")
        if not isinstance(itineraries, list):
            raise ProviderInvalidResponseError("OneMap PT itineraries were not a list")
        if not itineraries:
            raise ProviderNoRouteError("OneMap found no public-transport itineraries")

        itinerary = itineraries[0]
        if not isinstance(itinerary, dict):
            raise ProviderInvalidResponseError("OneMap PT itinerary had an unexpected shape")
        legs_payload = itinerary.get("legs")
        if legs_payload is None:
            legs_payload = []
        if not isinstance(legs_payload, list):
            raise ProviderInvalidResponseError("OneMap PT legs were not a list")

        legs: list[RouteLeg] = []
        nullable_fields: set[str] = set()
        for raw_leg in legs_payload:
            if not isinstance(raw_leg, dict):
                continue
            mode = str(raw_leg.get("mode") or "UNKNOWN").upper()
            from_place = raw_leg.get("from") if isinstance(raw_leg.get("from"), dict) else {}
            to_place = raw_leg.get("to") if isinstance(raw_leg.get("to"), dict) else {}
            geometry, geometry_format = _geometry(raw_leg)
            departure_time = _timestamp(
                raw_leg.get("startTime", raw_leg.get("departureTime"))
            )
            arrival_time = _timestamp(raw_leg.get("endTime", raw_leg.get("arrivalTime")))
            if departure_time is None:
                nullable_fields.add("leg.departure_time")
            if arrival_time is None:
                nullable_fields.add("leg.arrival_time")
            if geometry is None:
                nullable_fields.add("leg.geometry")
            legs.append(
                RouteLeg(
                    mode=mode,
                    duration_minutes=round(_number(raw_leg.get("duration")) / 60.0, 2),
                    distance_m=round(_number(raw_leg.get("distance")), 1),
                    from_name=from_place.get("name"),
                    to_name=to_place.get("name"),
                    departure_time=departure_time,
                    arrival_time=arrival_time,
                    geometry=geometry,
                    geometry_format=geometry_format,
                    route_short_name=_text(raw_leg.get("routeShortName"))
                    or _text(raw_leg.get("route")),
                    route_long_name=_text(raw_leg.get("routeLongName")),
                    agency=_text(raw_leg.get("agencyName")),
                    # intermediateStops excludes the boarding stop, so the
                    # number of stops ridden is one more than its length.
                    stop_count=(
                        len(raw_leg["intermediateStops"]) + 1
                        if isinstance(raw_leg.get("intermediateStops"), list)
                        else None
                    ),
                    from_stop_code=_text(from_place.get("stopCode")),
                    to_stop_code=_text(to_place.get("stopCode")),
                )
            )

        departure_time = _timestamp(
            itinerary.get("startTime", itinerary.get("departureTime"))
        )
        arrival_time = _timestamp(itinerary.get("endTime", itinerary.get("arrivalTime")))
        duration_seconds = _number(itinerary.get("duration"))
        duration_source = "itinerary.duration_seconds"
        if duration_seconds <= 0 and departure_time and arrival_time:
            duration_seconds = (arrival_time - departure_time).total_seconds()
            duration_source = "itinerary_time_difference"
        if duration_seconds <= 0:
            duration_seconds = sum(
                _number(leg.get("duration"))
                for leg in legs_payload
                if isinstance(leg, dict)
            )
            duration_source = "leg_duration_sum_seconds"
        if duration_seconds <= 0:
            raise ProviderInvalidResponseError("OneMap PT itinerary had no usable duration")

        walking_seconds = _number(itinerary.get("walkTime"))
        walking_time_source = "itinerary.walkTime_seconds"
        if walking_seconds <= 0:
            walking_seconds = sum(
                _number(leg.get("duration"))
                for leg in legs_payload
                if isinstance(leg, dict)
                and str(leg.get("mode", "")).upper() == "WALK"
            )
            walking_time_source = "walk_leg_duration_sum_seconds"

        walking_distance = _number(itinerary.get("walkDistance"))
        walking_distance_source = "itinerary.walkDistance_metres"
        if walking_distance <= 0:
            walking_distance = sum(leg.distance_m for leg in legs if leg.mode == "WALK")
            walking_distance_source = "walk_leg_distance_sum_metres"

        transfer_value = itinerary.get("transfers", itinerary.get("numTransfers"))
        if transfer_value is None:
            transit_legs = sum(
                1 for leg in legs if leg.mode not in {"WALK", "BICYCLE"}
            )
            transfers = max(0, transit_legs - 1)
            transfer_source = "inferred_transit_leg_changes"
        else:
            transfers = max(0, int(_number(transfer_value)))
            transfer_source = "itinerary_transfer_field"

        geometry_formats = sorted(
            {leg.geometry_format for leg in legs if leg.geometry_format}
        )
        return RouteResult(
            duration_minutes=round(duration_seconds / 60.0, 2),
            walking_minutes=round(walking_seconds / 60.0, 2),
            walking_distance_m=round(walking_distance, 1),
            transfers=transfers,
            legs=tuple(legs),
            provider="onemap",
            source_schema=f"onemap-pt-{schema_variant}-v2",
            raw_metadata={
                "itinerary_count": len(itineraries),
                "selected_itinerary_index": 0,
                "duration_source": duration_source,
                "walking_time_source": walking_time_source,
                "walking_distance_source": walking_distance_source,
                "transfer_source": transfer_source,
                "geometry_formats": geometry_formats,
                "nullable_fields": sorted(nullable_fields),
                "units": {
                    "duration": "seconds",
                    "distance": "metres",
                    "timestamps": "unix_ms_or_iso",
                },
            },
            departure_time=departure_time,
            arrival_time=arrival_time,
            time_dependent=bool(departure_time and arrival_time),
        )


_NORMALIZER = OneMapNormalizer()


def normalize_public_transport_response(payload: dict[str, Any]) -> RouteResult:
    """Compatibility wrapper around the isolated normalizer."""
    return _NORMALIZER.normalize_public_transport(payload)


class OneMapProvider(MapProvider):
    def __init__(
        self,
        base_url: str,
        email: str | None,
        password: str | None,
        timeout_seconds: float = 15.0,
        refresh_margin_seconds: int = 300,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.2,
        departure_time_routing_verified: bool = True,
        normalizer: OneMapNormalizer | None = None,
    ):
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._departure_time_routing_verified = departure_time_routing_verified
        self._normalizer = normalizer or OneMapNormalizer()
        self._tokens = OneMapTokenManager(
            self._client,
            self._base_url,
            email,
            password,
            refresh_margin_seconds,
        )

    @property
    def supports_departure_time_routing(self) -> bool:
        return self._departure_time_routing_verified

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _sleep_before_retry(
        self, retry_index: int, retry_after: str | None = None
    ) -> None:
        delay = self._retry_backoff_seconds * (2 ** max(0, retry_index - 1))
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), 2.0))
            except ValueError:
                pass
        if delay > 0:
            await asyncio.sleep(delay)

    async def _get(
        self, path: str, params: dict[str, Any]
    ) -> tuple[dict[str, Any], float, int]:
        started = time.perf_counter()
        transient_retries = 0
        token_refresh_used = False
        attempts = 0
        while True:
            attempts += 1
            token = await self._tokens.get_token(force_refresh=False)
            try:
                response = await self._client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers={"Authorization": token},
                )
            except httpx.TimeoutException as error:
                if transient_retries < self._max_retries:
                    transient_retries += 1
                    await self._sleep_before_retry(transient_retries)
                    continue
                raise ProviderTimeoutError(
                    "OneMap request timed out after bounded retries"
                ) from error
            except httpx.RequestError as error:
                if transient_retries < self._max_retries:
                    transient_retries += 1
                    await self._sleep_before_retry(transient_retries)
                    continue
                raise ProviderUpstreamError(
                    "OneMap request failed after bounded retries"
                ) from error

            if response.status_code in {401, 403}:
                if not token_refresh_used:
                    token_refresh_used = True
                    self._tokens.invalidate()
                    await self._tokens.get_token(force_refresh=True)
                    continue
                raise ProviderAuthenticationError(
                    "OneMap rejected the refreshed access token"
                )
            if response.status_code == 429:
                if transient_retries < self._max_retries:
                    transient_retries += 1
                    await self._sleep_before_retry(
                        transient_retries, response.headers.get("Retry-After")
                    )
                    continue
                raise ProviderRateLimitError(
                    "OneMap rate limit persisted after bounded retries"
                )
            if response.status_code >= 500:
                if transient_retries < self._max_retries:
                    transient_retries += 1
                    await self._sleep_before_retry(transient_retries)
                    continue
                raise ProviderUpstreamError(
                    f"OneMap upstream failure persisted after bounded retries "
                    f"(HTTP {response.status_code})"
                )
            if response.status_code == 404 and "routingsvc" in path:
                raise ProviderNoRouteError(
                    "OneMap found no route for the requested points"
                )
            if response.status_code >= 400:
                raise ProviderInvalidResponseError(
                    f"OneMap rejected the request (HTTP {response.status_code})"
                )
            try:
                payload = response.json()
            except ValueError as error:
                raise ProviderInvalidResponseError(
                    "OneMap returned non-JSON content"
                ) from error
            if not isinstance(payload, dict):
                raise ProviderInvalidResponseError(
                    "OneMap returned a non-object JSON value"
                )
            error_message = str(payload.get("error", ""))
            if error_message:
                lowered = error_message.casefold()
                if "token" in lowered:
                    if not token_refresh_used:
                        token_refresh_used = True
                        self._tokens.invalidate()
                        await self._tokens.get_token(force_refresh=True)
                        continue
                    raise ProviderAuthenticationError(
                        "OneMap reported a token failure after refresh"
                    )
                if "no route" in lowered or "no path" in lowered:
                    raise ProviderNoRouteError(
                        "OneMap found no route for the requested points"
                    )
                raise ProviderInvalidResponseError(
                    "OneMap returned an error payload"
                )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return payload, latency_ms, attempts

    async def geocode(self, query: str, limit: int = 5) -> list[GeocodeMatch]:
        payload, _, _ = await self._get(
            "/api/common/elastic/search",
            {
                "searchVal": query,
                "returnGeom": "Y",
                "getAddrDetails": "Y",
                "pageNum": 1,
            },
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise ProviderInvalidResponseError(
                "OneMap geocoder returned an unexpected shape"
            )
        matches: list[GeocodeMatch] = []
        for result in results[:limit]:
            if not isinstance(result, dict):
                continue
            try:
                coordinate = Coordinate(
                    float(result["LATITUDE"]),
                    float(result.get("LONGITUDE", result.get("LONGTITUDE"))),
                )
            except (KeyError, TypeError, ValueError):
                continue
            matches.append(
                GeocodeMatch(
                    label=str(
                        result.get("SEARCHVAL") or result.get("ADDRESS") or query
                    ),
                    coordinate=coordinate,
                    postal_code=(
                        str(result.get("POSTAL")) if result.get("POSTAL") else None
                    ),
                    address=str(result.get("ADDRESS")) if result.get("ADDRESS") else None,
                    entity_type=(
                        "station" if any(term in str(result.get("SEARCHVAL", "")).casefold()
                                         for term in ("mrt", "lrt", "station", "interchange"))
                        else "address"
                    ),
                )
            )
        return matches

    async def route_public_transport(
        self,
        start: Coordinate,
        end: Coordinate,
        departure: datetime | None = None,
    ) -> RouteResult:
        singapore_time = departure or datetime.now(SINGAPORE_TZ)
        payload, latency_ms, attempts = await self._get(
            "/api/public/routingsvc/route",
            {
                "start": f"{start.latitude},{start.longitude}",
                "end": f"{end.latitude},{end.longitude}",
                "routeType": "pt",
                "date": singapore_time.strftime("%m-%d-%Y"),
                "time": singapore_time.strftime("%H:%M:%S"),
                "mode": "TRANSIT",
            },
        )
        normalized = self._normalizer.normalize_public_transport(payload)
        return replace(
            normalized,
            raw_metadata={
                **normalized.raw_metadata,
                "provider_latency_ms": latency_ms,
                "provider_attempts": attempts,
                "departure_time_routing_verified": (
                    self.supports_departure_time_routing
                ),
            },
        )
