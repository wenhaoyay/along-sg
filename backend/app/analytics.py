from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from app.schemas import AnalyticsEventRequest, AnalyticsReportResponse


class AnalyticsRepository:
    """Minimal anonymous beta telemetry store; location data is not accepted."""

    def __init__(self, path: Path, retention_days: int = 90):
        self.path = path
        self.retention_days = max(1, retention_days)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS analytics_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    anonymous_user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    search_id TEXT,
                    event_type TEXT NOT NULL,
                    recommendation_key TEXT,
                    recommendation_rank INTEGER,
                    feedback_value TEXT,
                    feedback_reason TEXT,
                    parse_method TEXT,
                    latency_ms REAL
                );
                CREATE INDEX IF NOT EXISTS idx_analytics_occurred
                    ON analytics_events(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_analytics_user
                    ON analytics_events(anonymous_user_id);
                CREATE INDEX IF NOT EXISTS idx_analytics_type
                    ON analytics_events(event_type);
                """
            )
            cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
            connection.execute(
                "DELETE FROM analytics_events WHERE occurred_at < ?", (cutoff,)
            )

    def record(self, event: AnalyticsEventRequest) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO analytics_events(
                    event_id, occurred_at, anonymous_user_id, session_id, search_id,
                    event_type, recommendation_key, recommendation_rank,
                    feedback_value, feedback_reason, parse_method, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.event_id), datetime.now(UTC).isoformat(),
                    str(event.anonymous_user_id), str(event.session_id),
                    str(event.search_id) if event.search_id else None,
                    event.event_type.value, event.recommendation_key,
                    event.recommendation_rank, event.feedback_value,
                    event.feedback_reason, event.parse_method, event.latency_ms,
                ),
            )
            return cursor.rowcount == 1

    def report(self, now: datetime | None = None) -> AnalyticsReportResponse:
        current = now or datetime.now(UTC)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM analytics_events ORDER BY occurred_at"
            ).fetchall()
        counts = Counter(row["event_type"] for row in rows)
        users = {row["anonymous_user_id"] for row in rows}
        def search_ids(event_type: str) -> set[str]:
            return {
                row["search_id"]
                for row in rows
                if row["event_type"] == event_type and row["search_id"]
            }

        started_searches = search_ids("search_started")
        completed_searches = search_ids("optimization_completed")
        searches = len(started_searches) or counts["search_started"]
        completions = len(completed_searches) or counts["optimization_completed"]
        selections = [row for row in rows if row["event_type"] == "recommendation_selected"]
        alternatives = [row for row in rows if row["event_type"] == "alternative_selected"]
        selected_searches = {
            row["search_id"] for row in selections if row["search_id"]
        }
        latencies = sorted(
            float(row["latency_ms"])
            for row in rows
            if row["event_type"] == "optimization_completed" and row["latency_ms"] is not None
        )
        feedback = Counter(
            row["feedback_value"]
            for row in rows
            if row["event_type"] == "feedback_submitted" and row["feedback_value"]
        )
        reasons = Counter(
            row["feedback_reason"]
            for row in rows
            if row["event_type"] == "feedback_submitted" and row["feedback_reason"]
        )
        user_days: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            user_days[row["anonymous_user_id"]].add(row["occurred_at"][:10])
        today = current.date()
        seven_day_cutoff = today - timedelta(days=6)
        active_one_day = {
            row["anonymous_user_id"] for row in rows
            if datetime.fromisoformat(row["occurred_at"]).date() == today
        }
        active_seven_day = {
            row["anonymous_user_id"] for row in rows
            if datetime.fromisoformat(row["occurred_at"]).date() >= seven_day_cutoff
        }
        returning_users = sum(len(days) >= 2 for days in user_days.values())
        return AnalyticsReportResponse(
            generated_at=current,
            retention_days=self.retention_days,
            unique_anonymous_users=len(users),
            searches=searches,
            searches_per_user=round(searches / len(users), 3) if users else 0,
            completion_rate=round(completions / searches, 4) if searches else 0,
            parse_correction_rate=round(
                len(search_ids("interpretation_corrected")) / searches, 4
            ) if searches else 0,
            no_result_rate=round(
                len(search_ids("no_convenient_option")) / searches, 4
            ) if searches else 0,
            rank_one_acceptance_rate=round(
                len({
                    row["search_id"] for row in selections
                    if row["recommendation_rank"] == 1 and row["search_id"]
                }) / completions,
                4,
            ) if completions else 0,
            alternative_selection_rate=round(
                len({row["search_id"] for row in alternatives if row["search_id"]})
                / len(selected_searches),
                4,
            ) if selected_searches else 0,
            navigation_click_rate=round(
                len(search_ids("navigation_clicked")) / completions, 4
            ) if completions else 0,
            positive_feedback=feedback["positive"],
            negative_feedback=feedback["negative"],
            common_negative_feedback_reasons=dict(reasons.most_common()),
            median_optimization_latency_ms=round(median(latencies), 2) if latencies else None,
            p95_optimization_latency_ms=_percentile(latencies, 0.95),
            active_users_one_day=len(active_one_day),
            active_users_seven_day=len(active_seven_day),
            returning_users=returning_users,
            return_usage_rate=round(returning_users / len(users), 4) if users else 0,
            explicit_return_events=counts["return_usage"],
            event_counts=dict(sorted(counts.items())),
        )


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int((len(values) - 1) * quantile + 0.999999)))
    return round(values[index], 2)
