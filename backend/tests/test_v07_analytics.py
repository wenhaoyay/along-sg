from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.analytics import AnalyticsRepository
from app.config import Settings
from app.main import create_app
from app.schemas import AnalyticsEventRequest, AnalyticsEventType


def event(event_type: AnalyticsEventType, user=None, session=None, **values):
    return AnalyticsEventRequest(
        event_id=uuid4(), anonymous_user_id=user or uuid4(),
        session_id=session or uuid4(), event_type=event_type, **values,
    )


def test_anonymous_event_storage_aggregation_and_retention(tmp_path: Path):
    path = tmp_path / "analytics.db"
    repository = AnalyticsRepository(path, retention_days=30)
    repository.initialize()
    user, session, search = uuid4(), uuid4(), uuid4()
    repository.record(event(AnalyticsEventType.APP_OPENED, user, session))
    repository.record(event(AnalyticsEventType.SEARCH_STARTED, user, session, search_id=search))
    repository.record(event(AnalyticsEventType.INTENT_PARSED, user, session, search_id=search, parse_method="deterministic", latency_ms=4.2))
    repository.record(event(AnalyticsEventType.INTERPRETATION_CORRECTED, user, session, search_id=search))
    repository.record(event(AnalyticsEventType.OPTIMIZATION_COMPLETED, user, session, search_id=search, latency_ms=120))
    repository.record(event(AnalyticsEventType.RECOMMENDATION_SELECTED, user, session, search_id=search, recommendation_key="best_overall", recommendation_rank=1))
    repository.record(event(AnalyticsEventType.NAVIGATION_CLICKED, user, session, search_id=search, recommendation_key="best_overall"))
    repository.record(event(AnalyticsEventType.FEEDBACK_SUBMITTED, user, session, search_id=search, feedback_value="negative", feedback_reason="too_much_walking"))

    report = repository.report()
    assert report.unique_anonymous_users == 1
    assert report.searches == 1
    assert report.completion_rate == 1
    assert report.parse_correction_rate == 1
    assert report.rank_one_acceptance_rate == 1
    assert report.navigation_click_rate == 1
    assert report.negative_feedback == 1
    assert report.common_negative_feedback_reasons == {"too_much_walking": 1}
    assert report.median_optimization_latency_ms == 120
    assert report.p95_optimization_latency_ms == 120

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE analytics_events SET occurred_at=? WHERE event_type='app_opened'",
            ((datetime.now(UTC) - timedelta(days=31)).isoformat(),),
        )
    repository.initialize()
    assert repository.report().event_counts.get("app_opened", 0) == 0


def test_event_id_is_idempotent_and_payload_cannot_contain_location(tmp_path: Path):
    repository = AnalyticsRepository(tmp_path / "events.db")
    repository.initialize()
    item = event(AnalyticsEventType.APP_OPENED)
    assert repository.record(item)
    assert not repository.record(item)

    app = create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "poi.db",
        analytics_database_path=tmp_path / "api-analytics.db",
    ))
    payload = item.model_dump(mode="json") | {"latitude": 1.3, "longitude": 103.8}
    with TestClient(app) as client:
        response = client.post("/api/analytics/events", json=payload)
    assert response.status_code == 422


def test_admin_report_is_token_protected(tmp_path: Path):
    app = create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "poi.db",
        analytics_database_path=tmp_path / "analytics.db",
        beta_admin_token="test-admin-token",
    ))
    user, session = str(uuid4()), str(uuid4())
    payload = {
        "event_id": str(uuid4()), "anonymous_user_id": user,
        "session_id": session, "event_type": "search_started",
    }
    with TestClient(app) as client:
        assert client.post("/api/analytics/events", json=payload).status_code == 200
        assert client.get("/api/admin/analytics").status_code == 401
        assert client.get(
            "/api/admin/analytics", headers={"Authorization": "Bearer wrong"}
        ).status_code == 401
        report = client.get(
            "/api/admin/analytics",
            headers={"Authorization": "Bearer test-admin-token"},
        )
    assert report.status_code == 200
    assert report.json()["searches"] == 1


def test_admin_report_is_hidden_when_not_configured(tmp_path: Path):
    app = create_app(Settings(
        onemap_mock=True,
        database_path=tmp_path / "poi.db",
        analytics_database_path=tmp_path / "analytics.db",
    ))
    with TestClient(app) as client:
        assert client.get("/api/admin/analytics").status_code == 404


def test_report_uses_distinct_searches_and_detects_return_days(tmp_path: Path):
    repository = AnalyticsRepository(tmp_path / "returning.db")
    repository.initialize()
    user, session, search = uuid4(), uuid4(), uuid4()
    yesterday = event(AnalyticsEventType.APP_OPENED, user, session)
    repository.record(yesterday)
    repository.record(event(AnalyticsEventType.APP_OPENED, user, session))
    repository.record(event(AnalyticsEventType.RETURN_USAGE, user, session))
    for _ in range(2):
        repository.record(event(
            AnalyticsEventType.SEARCH_STARTED, user, session, search_id=search
        ))
        repository.record(event(
            AnalyticsEventType.OPTIMIZATION_COMPLETED,
            user,
            session,
            search_id=search,
            latency_ms=50,
        ))
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE analytics_events SET occurred_at=? WHERE event_id=?",
            (
                (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                str(yesterday.event_id),
            ),
        )

    report = repository.report()
    assert report.searches == 1
    assert report.completion_rate == 1
    assert report.returning_users == 1
    assert report.return_usage_rate == 1
    assert report.explicit_return_events == 1
    assert report.active_users_one_day == 1
    assert report.active_users_seven_day == 1
