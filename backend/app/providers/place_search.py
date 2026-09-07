from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from urllib.parse import quote

import httpx

from app.discovery_models import (
    CandidatePlaceEvidence,
    DiscoveryConfidence,
    DiscoverySearchContext,
    DiscoverySource,
    EvidenceTier,
    ResolvedPlace,
)
from app.domain import Coordinate


class LivePlaceSearchError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LivePlaceSearchProvider(ABC):
    name: str

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 8,
        context: DiscoverySearchContext | None = None,
        category_hint: str | None = None,
    ) -> list[ResolvedPlace]:
        raise NotImplementedError

    @property
    @abstractmethod
    def calls(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def cache_hits(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def latency_ms(self) -> float:
        raise NotImplementedError


class _CachedHttpProvider(LivePlaceSearchProvider):
    def __init__(self, timeout_seconds: float, cache_ttl_seconds: float, max_retries: int):
        self._ttl = cache_ttl_seconds
        self._max_retries = max(0, min(max_retries, 2))
        self._calls = 0
        self._cache_hits = 0
        self._latency_ms = 0.0
        self._cache: OrderedDict[str, tuple[float, list[ResolvedPlace]]] = OrderedDict()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def latency_ms(self) -> float:
        return round(self._latency_ms, 2)

    def _cached(self, key: str, limit: int) -> list[ResolvedPlace] | None:
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] <= self._ttl:
            self._cache_hits += 1
            self._cache.move_to_end(key)
            return cached[1][:limit]
        if cached:
            del self._cache[key]
        return None

    def _remember(self, key: str, places: list[ResolvedPlace]) -> None:
        self._cache[key] = (time.monotonic(), places)
        self._cache.move_to_end(key)
        while len(self._cache) > 64:
            self._cache.popitem(last=False)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            self._calls += 1
            started = time.perf_counter()
            try:
                response = await self._client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                self._latency_ms += (time.perf_counter() - started) * 1000
                if attempt >= self._max_retries:
                    raise LivePlaceSearchError(f"{self.name} place search timed out") from error
                await asyncio.sleep(0.15 * (2**attempt))
                continue
            self._latency_ms += (time.perf_counter() - started) * 1000
            if response.status_code in {401, 403}:
                raise LivePlaceSearchError(f"{self.name} authentication failed", response.status_code)
            if response.status_code == 429:
                if attempt < self._max_retries:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise LivePlaceSearchError(f"{self.name} rate limit reached")
            if response.status_code >= 500:
                if attempt < self._max_retries:
                    await asyncio.sleep(0.15 * (2**attempt))
                    continue
                raise LivePlaceSearchError(f"{self.name} unavailable")
            try:
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise LivePlaceSearchError(f"{self.name} rejected the search request") from error
            return response
        raise LivePlaceSearchError(f"{self.name} request failed")

    async def close(self) -> None:
        await self._client.aclose()


class TomTomPlaceSearchProvider(_CachedHttpProvider):
    """Backend-only TomTom Search API v2 adapter with bounded route bias."""

    name = "tomtom"

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: float = 300.0,
        hard_budget: int = 3,
        max_retries: int = 1,
    ):
        super().__init__(timeout_seconds, cache_ttl_seconds, max_retries)
        self._api_key = api_key
        self._hard_budget = max(1, hard_budget)

    async def search(
        self,
        query: str,
        limit: int = 8,
        context: DiscoverySearchContext | None = None,
        category_hint: str | None = None,
    ) -> list[ResolvedPlace]:
        center = context.center if context else None
        route = context.route_geometry if context else ()
        key = "|".join((" ".join(query.casefold().split()), str(limit), str(center), str(len(route))))
        cached = self._cached(key, limit)
        if cached is not None:
            return cached
        before = self.calls
        params: dict[str, str | int] = {
            "key": self._api_key, "countrySet": "SG", "limit": min(limit, 20),
            "language": "en-GB", "typeahead": "false", "view": "Unified",
        }
        if center:
            params.update({"lat": str(center.latitude), "lon": str(center.longitude), "radius": str(context.radius_m)})
        if route and len(route) >= 2:
            url = f"https://api.tomtom.com/search/2/alongRouteSearch/{quote(query)}.json"
            params["maxDetourTime"] = 900
            payload = {"route": {"points": [{"lat": point.latitude, "lon": point.longitude} for point in route[:100]]}}
            try:
                response = await self._request("POST", url, params=params, json=payload)
            except LivePlaceSearchError as error:
                if error.status_code != 403 or self.calls - before >= self._hard_budget:
                    raise
                # Live validation found that some otherwise-valid Search API keys
                # receive 403 for alongRouteSearch. Make one bounded fuzzy-search
                # fallback instead of misreporting the whole provider as unusable.
                params.pop("maxDetourTime", None)
                url = f"https://api.tomtom.com/search/2/search/{quote(query)}.json"
                response = await self._request("GET", url, params=params)
        else:
            url = f"https://api.tomtom.com/search/2/search/{quote(query)}.json"
            response = await self._request("GET", url, params=params)
        if self.calls - before > self._hard_budget:
            raise LivePlaceSearchError("TomTom discovery request hard budget reached")
        try:
            body = response.json()
        except ValueError as error:
            raise LivePlaceSearchError("TomTom returned an invalid response") from error
        places = self._normalize(body)
        self._remember(key, places)
        return places[:limit]

    @staticmethod
    def _normalize(body: dict) -> list[ResolvedPlace]:
        places: list[ResolvedPlace] = []
        for item in body.get("results", []):
            poi, address, position = item.get("poi") or {}, item.get("address") or {}, item.get("position") or {}
            if "lat" not in position or "lon" not in position:
                continue
            label = str(poi.get("name") or address.get("freeformAddress") or "").strip()
            if not label:
                continue
            categories = tuple(str(value) for value in poi.get("categories") or ())
            places.append(ResolvedPlace(
                display_name=label, canonical_name=label,
                coordinate=Coordinate(float(position["lat"]), float(position["lon"])),
                address=address.get("freeformAddress"), category=categories[0] if categories else None,
                source=DiscoverySource.TOMTOM, source_id=item.get("id"),
                confidence=DiscoveryConfidence.LIKELY, evidence=categories,
                provenance=(DiscoverySource.TOMTOM,), evidence_tier=EvidenceTier.SUPPORTED,
                structured_evidence=(CandidatePlaceEvidence(
                    source=DiscoverySource.TOMTOM, source_type="place_api", tier=EvidenceTier.SUPPORTED,
                    category_match=bool(categories), observed_text=(label, *categories),
                ),),
            ))
        return places


class GeoapifyPlaceSearchProvider(_CachedHttpProvider):
    """Geoapify free-text geocoder adapter, restricted and biased to Singapore."""

    name = "geoapify"

    def __init__(self, api_key: str, timeout_seconds: float = 5.0, cache_ttl_seconds: float = 300.0, max_retries: int = 1):
        super().__init__(timeout_seconds, cache_ttl_seconds, max_retries)
        self._api_key = api_key

    async def search(
        self,
        query: str,
        limit: int = 8,
        context: DiscoverySearchContext | None = None,
        category_hint: str | None = None,
    ) -> list[ResolvedPlace]:
        center = context.center if context else None
        key = "|".join((" ".join(query.casefold().split()), str(limit), str(center)))
        cached = self._cached(key, limit)
        if cached is not None:
            return cached
        params: dict[str, str | int] = {
            "text": f"{query}, Singapore", "format": "json", "filter": "countrycode:sg",
            "limit": min(limit, 20), "lang": "en", "apiKey": self._api_key,
        }
        if center:
            params["bias"] = f"proximity:{center.longitude},{center.latitude}"
        response = await self._request("GET", "https://api.geoapify.com/v1/geocode/search", params=params)
        try:
            body = response.json()
        except ValueError as error:
            raise LivePlaceSearchError("Geoapify returned an invalid response") from error
        places: list[ResolvedPlace] = []
        for item in body.get("results", []):
            if item.get("lat") is None or item.get("lon") is None:
                continue
            label = str(item.get("name") or item.get("formatted") or "").strip()
            if not label:
                continue
            categories = tuple(str(value) for value in item.get("categories") or ())
            places.append(ResolvedPlace(
                display_name=label, canonical_name=label,
                coordinate=Coordinate(float(item["lat"]), float(item["lon"])),
                address=item.get("formatted"), category=categories[0] if categories else item.get("result_type"),
                source=DiscoverySource.GEOAPIFY, source_id=item.get("place_id"),
                confidence=DiscoveryConfidence.LIKELY, evidence=categories,
                provenance=(DiscoverySource.GEOAPIFY,), evidence_tier=EvidenceTier.SUPPORTED,
                structured_evidence=(CandidatePlaceEvidence(
                    source=DiscoverySource.GEOAPIFY, source_type="place_geocoder", tier=EvidenceTier.SUPPORTED,
                    category_match=bool(categories), observed_text=(label, *categories),
                ),),
            ))
        self._remember(key, places)
        return places[:limit]


class MockLivePlaceSearchProvider(LivePlaceSearchProvider):
    name = "mock_live"

    def __init__(self, fixtures: dict[str, list[ResolvedPlace]] | None = None, fail: bool = False):
        self.fixtures = fixtures or {}
        self.fail = fail
        self._calls = 0
        self._cache_hits = 0

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def latency_ms(self) -> float:
        return 0.0

    async def search(
        self,
        query: str,
        limit: int = 8,
        context: DiscoverySearchContext | None = None,
        category_hint: str | None = None,
    ) -> list[ResolvedPlace]:
        self._calls += 1
        await asyncio.sleep(0)
        if self.fail:
            raise LivePlaceSearchError("mock provider failure")
        normalized = " ".join(query.casefold().split())
        return self.fixtures.get(
            normalized,
            self.fixtures.get(normalized.removesuffix(" singapore"), self.fixtures.get(f"{normalized} singapore", [])),
        )[:limit]
