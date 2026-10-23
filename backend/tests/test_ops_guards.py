"""Public-demo guards: body size, per-client rate limits, and analytics
being off unless enabled, bounded when on."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.analytics import AnalyticsRepository
from app.config import Settings
from app.main import create_app
from app.ops import OpsSettings, RateLimit, TokenBucketLimiter
from app.schemas import AnalyticsEventRequest, AnalyticsEventType

PUNGGOL = {"coordinate": {"latitude": 1.4052, "longitude": 103.9024}}
ORCHARD = {"coordinate": {"latitude": 1.3043, "longitude": 103.8322}}
NO_LIMITS = OpsSettings(rate_limit_enabled=False)


def client_for(tmp_path: Path, ops: OpsSettings = NO_LIMITS, **settings) -> TestClient:
    return TestClient(create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "poi.db",
        analytics_database_path=tmp_path / "analytics.db",
        **settings,
    ), ops))


def optimize_body(**values) -> dict:
    return {"origin": PUNGGOL, "destination": ORCHARD, "errands": ["groceries"], **values}


def intent_body(**values) -> dict:
    return {
        "origin": PUNGGOL,
        "destination": ORCHARD,
        "intent": {
            "original_text": "groceries",
            "required_errands": [{"category": "groceries", "required": True}],
        },
        **values,
    }


# Body size ----------------------------------------------------------------

def test_oversized_body_is_refused_before_parsing(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = client.post("/api/optimize", json=optimize_body(errands=["x" * 20_000]))
        assert response.status_code == 413
        assert response.json() == {"detail": "Request body too large.", "max_bytes": 16384}

        def chunks():
            yield b'{"errands": ["'
            for _ in range(40):
                yield b"x" * 1024
            yield b'"]}'

        streamed = client.post(
            "/api/optimize", content=chunks(), headers={"content-type": "application/json"}
        )
        assert streamed.status_code == 413
        # An ordinary request still gets through with its body intact.
        assert client.post("/api/optimize", json=optimize_body()).status_code == 200


# Rate limits --------------------------------------------------------------

def test_token_bucket_refills_over_time() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter({"plan": RateLimit(burst=2, per_minute=6)}, clock=lambda: now[0])
    assert limiter.acquire("plan", "a") == 0
    assert limiter.acquire("plan", "a") == 0
    assert limiter.acquire("plan", "a") == pytest.approx(10.0)
    assert limiter.acquire("plan", "b") == 0  # Each client has its own bucket.
    now[0] = 10.0
    assert limiter.acquire("plan", "a") == 0


def test_expensive_routes_answer_429_with_retry_after(tmp_path: Path) -> None:
    ops = OpsSettings(rate_limits={
        "plan": RateLimit(burst=2, per_minute=1),
        "lookup": RateLimit(burst=1, per_minute=1),
        "analytics": RateLimit(burst=1, per_minute=1),
    })
    with client_for(tmp_path, ops) as client:
        assert client.post("/api/optimize", json=optimize_body()).status_code == 200
        # The plan bucket is shared by both planning routes.
        assert client.post("/api/optimize-intent", json=intent_body()).status_code == 200
        limited = client.post("/api/optimize", json=optimize_body())
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
        assert limited.json()["detail"] == "Too many requests. Try again shortly."
        assert limited.json()["retry_after_seconds"] == int(limited.headers["retry-after"])
        assert client.get("/api/geocode", params={"q": "Punggol"}).status_code == 200
        assert client.get("/api/geocode", params={"q": "Punggol"}).status_code == 429
        # Cheap routes are never limited.
        for _ in range(5):
            assert client.get("/health").status_code == 200
            assert client.get("/api/catalog/categories").status_code == 200


# Analytics ----------------------------------------------------------------

def event_payload() -> dict:
    return {
        "event_id": str(uuid4()), "anonymous_user_id": str(uuid4()),
        "session_id": str(uuid4()), "event_type": "app_opened",
    }


def test_analytics_is_off_by_default(tmp_path: Path) -> None:
    assert OpsSettings().analytics_enabled is False
    with client_for(tmp_path, beta_admin_token="token") as client:
        assert client.post("/api/analytics/events", json=event_payload()).status_code == 404
        assert client.get(
            "/api/admin/analytics", headers={"Authorization": "Bearer token"}
        ).status_code == 404
    assert not (tmp_path / "analytics.db").exists()


def test_analytics_when_enabled_records_events(tmp_path: Path) -> None:
    ops = OpsSettings(rate_limit_enabled=False, analytics_enabled=True)
    with client_for(tmp_path, ops) as client:
        response = client.post("/api/analytics/events", json=event_payload())
    assert response.status_code == 200
    assert response.json() == {"accepted": True}


def analytics_event() -> AnalyticsEventRequest:
    return AnalyticsEventRequest(
        event_id=uuid4(), anonymous_user_id=uuid4(), session_id=uuid4(),
        event_type=AnalyticsEventType.APP_OPENED,
    )


def test_analytics_row_cap_and_purge_run_while_recording(tmp_path: Path) -> None:
    repository = AnalyticsRepository(
        tmp_path / "capped.db", retention_days=30, max_rows=5, purge_every_inserts=3,
    )
    repository.initialize()
    for _ in range(12):
        repository.record(analytics_event())
    with sqlite3.connect(repository.path) as connection:
        stored = connection.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0]
    # Never more than the cap plus one purge interval of new rows.
    assert stored <= 5 + 3
    repository.purge()
    assert repository.report().event_counts == {"app_opened": 5}

    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE analytics_events SET occurred_at=?",
            ((datetime.now(UTC) - timedelta(days=31)).isoformat(),),
        )
    assert repository.purge() == 5
    assert repository.report().event_counts == {}


def test_analytics_report_aggregates_latency_in_sql(tmp_path: Path) -> None:
    repository = AnalyticsRepository(tmp_path / "latency.db")
    repository.initialize()
    for latency in (10, 40, 20, 30):
        repository.record(AnalyticsEventRequest(
            event_id=uuid4(), anonymous_user_id=uuid4(), session_id=uuid4(),
            search_id=uuid4(), event_type=AnalyticsEventType.OPTIMIZATION_COMPLETED,
            latency_ms=latency,
        ))
    report = repository.report()
    assert report.median_optimization_latency_ms == 25
    assert report.p95_optimization_latency_ms == 40
    assert report.unique_anonymous_users == 4
    assert report.active_users_one_day == 4
