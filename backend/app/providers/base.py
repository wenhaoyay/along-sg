from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.domain import Coordinate, GeocodeMatch, RouteResult


class ProviderError(RuntimeError):
    """An upstream mapping provider failed or returned an unusable response."""


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderUpstreamError(ProviderError):
    pass


class ProviderInvalidResponseError(ProviderError):
    pass


class ProviderNoRouteError(ProviderError):
    pass


class MapProvider(ABC):
    @property
    def supports_departure_time_routing(self) -> bool:
        return False

    @abstractmethod
    async def geocode(self, query: str, limit: int = 5) -> list[GeocodeMatch]:
        raise NotImplementedError

    @abstractmethod
    async def route_public_transport(
        self,
        start: Coordinate,
        end: Coordinate,
        departure: datetime | None = None,
    ) -> RouteResult:
        raise NotImplementedError
