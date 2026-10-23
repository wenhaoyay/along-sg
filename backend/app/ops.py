"""Operational guards for a public demo: body size, per-client rate limits.

Kept apart from `config.Settings` on purpose: these settings belong to the
deployment, not to journey planning, and they are read from the environment
the same way (`OpsSettings.from_env`).

Both guards are plain ASGI middleware, so they answer before FastAPI parses
or validates anything - an oversized or over-quota request costs nothing.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RateLimit:
    """A token bucket: `burst` requests at once, refilled at `per_minute`."""

    burst: int
    per_minute: float


# Which paths share which bucket. Planning routes many journeys per request;
# lookups are cheaper but can reach live providers.
RATE_LIMITED_PATHS: dict[str, str] = {
    "/api/optimize": "plan",
    "/api/optimize-intent": "plan",
    "/api/intent/parse": "lookup",
    "/api/journey": "lookup",
    "/api/geocode": "lookup",
    "/api/discovery/needs": "lookup",
    "/api/catalog/search": "lookup",
    "/api/analytics/events": "analytics",
}


@dataclass(frozen=True)
class OpsSettings:
    max_request_body_bytes: int = 16 * 1024
    rate_limit_enabled: bool = True
    rate_limits: dict[str, RateLimit] = field(default_factory=lambda: {
        "plan": RateLimit(burst=10, per_minute=12),
        "lookup": RateLimit(burst=30, per_minute=60),
        "analytics": RateLimit(burst=30, per_minute=60),
    })
    # Most clients remembered at once; the least recently seen is forgotten
    # first, which at worst hands that client a fresh bucket.
    rate_limit_max_clients: int = 10_000
    # Off unless asked for: nothing in the shipped frontend sends events.
    analytics_enabled: bool = False
    analytics_max_rows: int = 100_000
    analytics_purge_interval_seconds: float = 3600.0

    @classmethod
    def from_env(cls) -> "OpsSettings":
        defaults = cls()
        limits = dict(defaults.rate_limits)
        for name in limits:
            prefix = f"RATE_LIMIT_{name.upper()}"
            limits[name] = RateLimit(
                burst=int(os.getenv(f"{prefix}_BURST", str(limits[name].burst))),
                per_minute=float(os.getenv(f"{prefix}_PER_MINUTE", str(limits[name].per_minute))),
            )
        return cls(
            max_request_body_bytes=int(
                os.getenv("MAX_REQUEST_BODY_BYTES", str(defaults.max_request_body_bytes))
            ),
            rate_limit_enabled=_bool_env("RATE_LIMIT_ENABLED", defaults.rate_limit_enabled),
            rate_limits=limits,
            rate_limit_max_clients=int(
                os.getenv("RATE_LIMIT_MAX_CLIENTS", str(defaults.rate_limit_max_clients))
            ),
            analytics_enabled=_bool_env("ANALYTICS_ENABLED", defaults.analytics_enabled),
            analytics_max_rows=int(
                os.getenv("ANALYTICS_MAX_ROWS", str(defaults.analytics_max_rows))
            ),
            analytics_purge_interval_seconds=float(
                os.getenv(
                    "ANALYTICS_PURGE_INTERVAL_SECONDS",
                    str(defaults.analytics_purge_interval_seconds),
                )
            ),
        )


class TokenBucketLimiter:
    """In-process token buckets keyed by (bucket name, client address).

    One process, one worker: the deployment runs a single uvicorn worker, so
    nothing needs sharing. Not thread-safe; it is only called from the event
    loop.
    """

    def __init__(
        self,
        limits: dict[str, RateLimit],
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limits = limits
        self.max_clients = max(1, max_clients)
        self.clock = clock
        self._buckets: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()

    def acquire(self, bucket: str, client: str) -> float:
        """Take a token. Returns 0 when allowed, else seconds until one is due."""
        limit = self.limits[bucket]
        rate = limit.per_minute / 60.0
        now = self.clock()
        key = (bucket, client)
        tokens, updated = self._buckets.get(key, (float(limit.burst), now))
        tokens = min(float(limit.burst), tokens + (now - updated) * rate)
        if tokens >= 1.0:
            allowed, tokens = True, tokens - 1.0
        else:
            allowed = False
        self._buckets[key] = (tokens, now)
        self._buckets.move_to_end(key)
        while len(self._buckets) > self.max_clients:
            self._buckets.popitem(last=False)
        if allowed:
            return 0.0
        return (1.0 - tokens) / rate if rate > 0 else math.inf


async def _send_json(send: Send, status: int, body: dict[str, Any], headers: list[tuple[bytes, bytes]] = ()) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
            *headers,
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class RateLimitMiddleware:
    """429 with Retry-After once a client has spent its bucket.

    The client is `scope["client"]`, which uvicorn rewrites from
    X-Forwarded-For only when the connecting peer is a trusted proxy
    (`--proxy-headers`, `FORWARDED_ALLOW_IPS`). Never read the header here:
    anyone can send one.
    """

    def __init__(self, app: ASGIApp, limiter: TokenBucketLimiter, paths: dict[str, str] | None = None):
        self.app = app
        self.limiter = limiter
        self.paths = RATE_LIMITED_PATHS if paths is None else paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        bucket = self.paths.get(scope.get("path", ""))
        if bucket is None:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        address = client[0] if client else "unknown"
        wait = self.limiter.acquire(bucket, address)
        if wait <= 0:
            await self.app(scope, receive, send)
            return
        retry_after = max(1, math.ceil(wait)) if math.isfinite(wait) else 3600
        await _send_json(
            send, 429,
            {
                "detail": "Too many requests. Try again shortly.",
                "retry_after_seconds": retry_after,
            },
            [(b"retry-after", str(retry_after).encode("ascii"))],
        )


class BodySizeLimitMiddleware:
    """413 for a request body over the limit, declared or streamed.

    The body is read here, before the app sees it, and replayed: bodies under
    the limit are small, and an exception raised mid-read inside FastAPI would
    come out as its own 400 rather than a 413.
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send: Send) -> None:
        await _send_json(send, 413, {
            "detail": "Request body too large.",
            "max_bytes": self.max_bytes,
        })

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._reject(send)
                    return
        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # The client went away before finishing its request.
            body = message.get("body", b"")
            received += len(body)
            if received > self.max_bytes:
                await self._reject(send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
