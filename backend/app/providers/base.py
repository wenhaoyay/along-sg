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


class LocationNotFoundError(ProviderError):
    """The user's text names no Singapore place we can find: their input to
    fix, not an upstream failure, so it is a 422 and never a 502."""

    def __init__(self, message: str, suggestions: tuple[str, ...] = ()):
        super().__init__(message)
        self.suggestions = suggestions


class LocationAmbiguousError(LocationNotFoundError):
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
