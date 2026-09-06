from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


class WebDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebCandidate:
    title: str
    url: str
    snippet: str
    score: float | None = None


class WebDiscoveryProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[WebCandidate]: ...

    @property
    @abstractmethod
    def calls(self) -> int: ...

    @property
    @abstractmethod
    def latency_ms(self) -> float: ...


class TavilyWebDiscoveryProvider(WebDiscoveryProvider):
    name = "tavily"

    def __init__(self, api_key: str, timeout_seconds: float = 6.0):
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self._calls = 0
        self._latency_ms = 0.0

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def latency_ms(self) -> float:
        return round(self._latency_ms, 2)

    async def search(self, query: str, limit: int = 5) -> list[WebCandidate]:
        self._calls += 1
        started = time.perf_counter()
        try:
            response = await self._client.post("https://api.tavily.com/search", json={
                "api_key": self._api_key, "query": f"{query} Singapore",
                "search_depth": "basic", "max_results": min(limit, 8),
                "include_answer": False, "include_raw_content": False,
            })
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise WebDiscoveryError("Tavily search timed out") from error
        finally:
            self._latency_ms += (time.perf_counter() - started) * 1000
        if response.status_code in {401, 403}:
            raise WebDiscoveryError("Tavily authentication failed")
        if response.status_code == 429:
            raise WebDiscoveryError("Tavily rate limit reached")
        if response.status_code >= 500:
            raise WebDiscoveryError("Tavily unavailable")
        try:
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise WebDiscoveryError("Tavily returned an invalid response") from error
        return [WebCandidate(
            title=str(item.get("title") or "").strip(), url=str(item.get("url") or ""),
            snippet=str(item.get("content") or "")[:600], score=item.get("score"),
        ) for item in body.get("results", []) if item.get("title") and item.get("url")][:limit]

    async def close(self) -> None:
        await self._client.aclose()


class MockWebDiscoveryProvider(WebDiscoveryProvider):
    name = "mock_web"

    def __init__(self, fixtures: dict[str, list[WebCandidate]] | None = None, fail: bool = False):
        self.fixtures = fixtures or {}
        self.fail = fail
        self._calls = 0

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def latency_ms(self) -> float:
        return 0.0

    async def search(self, query: str, limit: int = 5) -> list[WebCandidate]:
        self._calls += 1
        await asyncio.sleep(0)
        if self.fail:
            raise WebDiscoveryError("mock web failure")
        return self.fixtures.get(" ".join(query.casefold().split()), [])[:limit]
