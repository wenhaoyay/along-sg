"""Live bus arrivals from LTA DataMall.

OneMap already says which bus to take; this says when it is coming. The join is
exact rather than fuzzy: OneMap hands back the operator's own `stopCode` on
every transit leg, and for a bus leg that is the same five-digit BusStopCode
DataMall is keyed on - so no name or coordinate matching is involved.

Two things in LTA's contract shape this module.

`Monitored` says whether an estimate came from the bus's actual location (1) or
from the operator's timetable (0). Those are different claims, and the app says
which one it is holding - the same way it already separates a checked route from
an estimated dwell.

And when buses are not running there is no response at all, not even the
attribute tags. Absence is normal here and must not read as an error.

Contract: LTA DataMall API User Guide v6.9 (3 Aug 2026), sections 2.1-2.4. The
data is served under the Singapore Open Data Licence, which - unlike the place
providers this project weighed up for opening hours - permits storing it and
serving it onward with attribution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import httpx

from app.domain import SINGAPORE_TZ, ArrivalEstimate, BusArrival
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)

logger = logging.getLogger("journey_optimizer")

DATAMALL_BASE_URL = "https://datamall2.mytransport.sg/ltaodataservice"

# The feed refreshes every 20 seconds, so a longer window serves a stale number
# as though it were live and a shorter one just spends quota.
ARRIVAL_CACHE_TTL_SECONDS = 20.0

ATTRIBUTION = "Bus arrival data (c) Land Transport Authority, Singapore Open Data Licence"

_OPERATORS = {
    "SBST": "SBS Transit",
    "SMRT": "SMRT",
    "TTS": "Tower Transit",
    "GAS": "Go-Ahead Singapore",
}


def operator_name(code: str | None) -> str | None:
    if not code:
        return None
    return _OPERATORS.get(code.upper(), code)


class BusArrivalProvider(ABC):
    """Arrivals at one stop, optionally narrowed to one service."""

    @abstractmethod
    async def arrivals(
        self, stop_code: str, service_no: str | None = None
    ) -> tuple[BusArrival, ...]:
        raise NotImplementedError

    async def close(self) -> None:
        return None


def _estimate(payload: object) -> ArrivalEstimate | None:
    """One oncoming bus, or None when the slot is padding.

    NextBus2 and NextBus3 arrive as fully-formed objects with every value blank
    when there is no second or third bus, so an empty EstimatedArrival is the
    only reliable signal that a slot is unfilled.
    """
    if not isinstance(payload, dict):
        return None
    raw = str(payload.get("EstimatedArrival") or "").strip()
    if not raw:
        return None
    try:
        arrival = datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("datamall_unparsable_arrival value=%r", raw[:40])
        return None
    if arrival.tzinfo is None:
        arrival = arrival.replace(tzinfo=SINGAPORE_TZ)
    load = str(payload.get("Load") or "").strip().upper() or None
    return ArrivalEstimate(
        arrival_time=arrival,
        # Documented as 0/1, delivered as an int by LTA and as a string by some
        # proxies, so the comparison is on the text.
        live=str(payload.get("Monitored", "")).strip() == "1",
        load=load if load in {"SEA", "SDA", "LSD"} else None,
        wheelchair_accessible=str(payload.get("Feature") or "").strip().upper() == "WAB",
        vehicle_type=str(payload.get("Type") or "").strip().upper() or None,
    )


def parse_arrivals(payload: dict) -> tuple[BusArrival, ...]:
    """Normalise one BusArrival response.

    A module function so the contract can be tested against LTA's own published
    sample without a client, a key or a network.
    """
    services = payload.get("Services")
    if not isinstance(services, list):
        # Not an error. An absent body is how LTA reports "nothing running", and
        # a stop with nothing due looks the same.
        return ()
    arrivals: list[BusArrival] = []
    for service in services:
        if not isinstance(service, dict):
            continue
        estimates = tuple(
            estimate
            for estimate in (
                _estimate(service.get(slot)) for slot in ("NextBus", "NextBus2", "NextBus3")
            )
            if estimate is not None
        )
        if not estimates:
            continue
        arrivals.append(
            BusArrival(
                service_no=str(service.get("ServiceNo") or "").strip(),
                operator=operator_name(service.get("Operator")),
                estimates=estimates,
            )
        )
    # Soonest first: a stop can serve a dozen routes, and the traveller is
    # looking for one of them rather than reading the list end to end.
    return tuple(sorted(arrivals, key=lambda item: item.estimates[0].arrival_time))


class LtaDataMallProvider(BusArrivalProvider):
    def __init__(
        self,
        account_key: str,
        base_url: str = DATAMALL_BASE_URL,
        timeout_seconds: float = 8.0,
        max_retries: int = 1,
        cache_ttl_seconds: float = ARRIVAL_CACHE_TTL_SECONDS,
    ):
        if not account_key:
            raise ProviderAuthenticationError("DataMall requires an AccountKey")
        self._key = account_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, min(max_retries, 2))
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[float, tuple[BusArrival, ...]]] = {}
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def arrivals(
        self, stop_code: str, service_no: str | None = None
    ) -> tuple[BusArrival, ...]:
        key = f"{stop_code}|{service_no or ''}"
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self._cache_ttl:
            return cached[1]
        params = {"BusStopCode": stop_code}
        if service_no:
            params["ServiceNo"] = service_no
        parsed = parse_arrivals(await self._get("/v3/BusArrival", params))
        self._cache[key] = (time.monotonic(), parsed)
        return parsed

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers={"AccountKey": self._key, "accept": "application/json"},
                )
            except httpx.TimeoutException as error:
                last_error = ProviderTimeoutError("DataMall timed out")
                if attempt >= self._max_retries:
                    raise last_error from error
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            except httpx.HTTPError as error:
                raise ProviderUpstreamError(f"DataMall request failed: {error}") from error
            if response.status_code in {401, 403}:
                raise ProviderAuthenticationError("DataMall rejected the AccountKey")
            if response.status_code == 429:
                raise ProviderRateLimitError("DataMall rate limit reached")
            if response.status_code >= 500:
                last_error = ProviderUpstreamError(f"DataMall returned {response.status_code}")
                if attempt >= self._max_retries:
                    raise last_error
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            if response.status_code != 200:
                raise ProviderUpstreamError(f"DataMall returned {response.status_code}")
            if not response.content.strip():
                # Documented: no body at all when nothing is running.
                return {}
            try:
                body = response.json()
            except ValueError as error:
                raise ProviderInvalidResponseError("DataMall returned non-JSON") from error
            if not isinstance(body, dict):
                raise ProviderInvalidResponseError("DataMall returned an unexpected shape")
            return body
        raise last_error or ProviderUpstreamError("DataMall request failed")

    async def close(self) -> None:
        await self._client.aclose()


class MockBusArrivalProvider(BusArrivalProvider):
    """Deterministic arrivals, so the feature is developable without a key.

    Seeded from the stop code, so a given stop answers the same way within a
    minute, and deliberately mixed: some services report live and some from the
    timetable, and one reserved code reports nothing at all - the three states
    the interface has to render.
    """

    QUIET_STOP_CODE = "00000"

    def __init__(self, services: tuple[str, ...] = ("95", "196", "48")):
        self._services = services

    async def arrivals(
        self, stop_code: str, service_no: str | None = None
    ) -> tuple[BusArrival, ...]:
        if stop_code == self.QUIET_STOP_CODE:
            return ()
        now = datetime.now(SINGAPORE_TZ).replace(second=0, microsecond=0)
        seed = sum(ord(character) for character in stop_code)
        wanted = (service_no,) if service_no else self._services
        arrivals: list[BusArrival] = []
        for index, service in enumerate(wanted):
            if not service:
                continue
            first = 2 + (seed + index * 7) % 9
            arrivals.append(
                BusArrival(
                    service_no=service,
                    operator="SBS Transit" if index % 2 == 0 else "Tower Transit",
                    estimates=tuple(
                        ArrivalEstimate(
                            arrival_time=now + timedelta(minutes=first + step * 8),
                            live=index % 2 == 0,
                            load=("SEA", "SDA", "LSD")[(seed + step) % 3],
                            wheelchair_accessible=step % 2 == 0,
                            vehicle_type="DD" if index == 1 else "SD",
                        )
                        for step in range(3 if index == 0 else 2)
                    ),
                )
            )
        return tuple(sorted(arrivals, key=lambda item: item.estimates[0].arrival_time))
