from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.domain import Coordinate
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderNoRouteError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from app.providers.onemap import OneMapProvider


VALID_ROUTE = {
    "plan": {
        "itineraries": [
            {
                "duration": 600,
                "walkTime": 120,
                "walkDistance": 150,
                "transfers": 0,
                "legs": [],
            }
        ]
    }
}


def _auth_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": "test-token", "expiry_timestamp": "4102444800"},
    )


async def _route_with_handler(handler) -> tuple[OneMapProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OneMapProvider(
        "https://example.test",
        "email",
        "password",
        client=client,
        max_retries=2,
        retry_backoff_seconds=0,
    )
    return provider, client


async def test_transient_5xx_is_retried_then_succeeds() -> None:
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal route_calls
        if "getToken" in request.url.path:
            return _auth_response()
        route_calls += 1
        return httpx.Response(503) if route_calls == 1 else httpx.Response(200, json=VALID_ROUTE)

    provider, client = await _route_with_handler(handler)
    try:
        route = await provider.route_public_transport(
            Coordinate(1.3, 103.8), Coordinate(1.31, 103.81)
        )
        assert route.duration_minutes == 10
        assert route.raw_metadata["provider_attempts"] == 2
        assert route_calls == 2
    finally:
        await client.aclose()


async def test_public_transport_request_uses_live_verified_date_format() -> None:
    observed_date = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_date
        if "getToken" in request.url.path:
            return _auth_response()
        observed_date = request.url.params.get("date")
        return httpx.Response(200, json=VALID_ROUTE)

    provider, client = await _route_with_handler(handler)
    try:
        await provider.route_public_transport(
            Coordinate(1.3, 103.8),
            Coordinate(1.31, 103.81),
            datetime(2026, 8, 27, 9, 30),
        )
        assert observed_date == "08-27-2026"
    finally:
        await client.aclose()


async def test_persistent_5xx_retries_are_bounded() -> None:
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal route_calls
        if "getToken" in request.url.path:
            return _auth_response()
        route_calls += 1
        return httpx.Response(502)

    provider, client = await _route_with_handler(handler)
    try:
        with pytest.raises(ProviderUpstreamError):
            await provider.route_public_transport(
                Coordinate(1.3, 103.8), Coordinate(1.31, 103.81)
            )
        assert route_calls == 3
    finally:
        await client.aclose()


async def test_route_auth_failure_refreshes_token_only_once() -> None:
    auth_calls = 0
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, route_calls
        if "getToken" in request.url.path:
            auth_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{auth_calls}",
                    "expiry_timestamp": "4102444800",
                },
            )
        route_calls += 1
        if route_calls == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "token-2"
        return httpx.Response(200, json=VALID_ROUTE)

    provider, client = await _route_with_handler(handler)
    try:
        result = await provider.route_public_transport(
            Coordinate(1.3, 103.8), Coordinate(1.31, 103.81)
        )
        assert result.duration_minutes == 10
        assert auth_calls == 2
        assert route_calls == 2
    finally:
        await client.aclose()



async def test_rate_limit_retries_are_bounded() -> None:
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal route_calls
        if "getToken" in request.url.path:
            return _auth_response()
        route_calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    provider, client = await _route_with_handler(handler)
    try:
        with pytest.raises(ProviderRateLimitError):
            await provider.route_public_transport(
                Coordinate(1.3, 103.8), Coordinate(1.31, 103.81)
            )
        assert route_calls == 3
    finally:
        await client.aclose()


async def test_timeout_retries_are_bounded() -> None:
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal route_calls
        if "getToken" in request.url.path:
            return _auth_response()
        route_calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    provider, client = await _route_with_handler(handler)
    try:
        with pytest.raises(ProviderTimeoutError):
            await provider.route_public_transport(
                Coordinate(1.3, 103.8), Coordinate(1.31, 103.81)
            )
        assert route_calls == 3
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("route_response", "error_type"),
    [
        (httpx.Response(404), ProviderNoRouteError),
        (httpx.Response(200, text="not-json"), ProviderInvalidResponseError),
    ],
)
async def test_no_route_and_invalid_json_are_not_retried(
    route_response: httpx.Response, error_type: type[Exception]
) -> None:
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal route_calls
        if "getToken" in request.url.path:
            return _auth_response()
        route_calls += 1
        return route_response

    provider, client = await _route_with_handler(handler)
    try:
        with pytest.raises(error_type):
            await provider.route_public_transport(
                Coordinate(1.3, 103.8), Coordinate(1.31, 103.81)
            )
        assert route_calls == 1
    finally:
        await client.aclose()


async def test_authentication_failure_is_explicit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    provider, client = await _route_with_handler(handler)
    try:
        with pytest.raises(ProviderAuthenticationError):
            await provider.route_public_transport(
                Coordinate(1.3, 103.8), Coordinate(1.31, 103.81)
            )
    finally:
        await client.aclose()
