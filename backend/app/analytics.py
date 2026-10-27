from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas import AnalyticsEventRequest, AnalyticsReportResponse


class AnalyticsRepository:
    """Minimal anonymous beta telemetry store; location data is not accepted.

    Bounded three ways: events older than the retention window are deleted,
    the table never keeps more than `max_rows` (oldest go first), and both
    rules run at startup, every `purge_every_inserts` events, and on the
    app's purge timer - not only when the process restarts.
    """

    def __init__(
        self,
        path: Path,
        retention_days: int = 90,
        max_rows: int = 100_000,
        purge_every_inserts: int = 500,
    ):
        self.path = path
        self.retention_days = max(1, retention_days)
        self.max_rows = max(1, max_rows)
        self.purge_every_inserts = max(1, purge_every_inserts)
        self._inserts_since_purge = 0

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
        self.purge()

    def purge(self, now: datetime | None = None) -> int:
        """Delete expired events, then the oldest beyond the row cap."""
        cutoff = ((now or datetime.now(UTC)) - timedelta(days=self.retention_days)).isoformat()
        with self._connect() as connection:
            expired = connection.execute(
                "DELETE FROM analytics_events WHERE occurred_at < ?", (cutoff,)
            ).rowcount
            excess = connection.execute(
                """
                DELETE FROM analytics_events WHERE rowid IN (
                    SELECT rowid FROM analytics_events
                    ORDER BY occurred_at DESC, rowid DESC LIMIT -1 OFFSET ?
                )
                """,
                (self.max_rows,),
            ).rowcount
        self._inserts_since_purge = 0
        return expired + excess

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
            accepted = cursor.rowcount == 1
        if accepted:
            self._inserts_since_purge += 1
            if self._inserts_since_purge >= self.purge_every_inserts:
                self.purge()
        return accepted

    def report(self, now: datetime | None = None) -> AnalyticsReportResponse:
        """Aggregated in SQL: the report never loads the event rows themselves."""
        current = now or datetime.now(UTC)
        today = current.date()
        seven_day_cutoff = today - timedelta(days=6)
        day = "substr(occurred_at, 1, 10)"
        latency_rows = (
            "FROM analytics_events WHERE event_type='optimization_completed' "
            "AND latency_ms IS NOT NULL"
        )
        with self._connect() as connection:
            def scalar(query: str, parameters: tuple = ()) -> int:
                return int(connection.execute(query, parameters).fetchone()[0] or 0)

            def distinct_searches(event_type: str, extra: str = "") -> int:
                return scalar(
                    "SELECT COUNT(DISTINCT search_id) FROM analytics_events "
                    f"WHERE event_type=? AND search_id IS NOT NULL {extra}",
                    (event_type,),
                )

            def latency_at(index: int) -> float:
                return float(connection.execute(
                    f"SELECT latency_ms {latency_rows} ORDER BY latency_ms LIMIT 1 OFFSET ?",
                    (index,),
                ).fetchone()[0])

            counts = {
                row[0]: int(row[1]) for row in connection.execute(
                    "SELECT event_type, COUNT(*) FROM analytics_events GROUP BY event_type"
                )
            }
            users = scalar("SELECT COUNT(DISTINCT anonymous_user_id) FROM analytics_events")
            searches = distinct_searches("search_started") or counts.get("search_started", 0)
            completions = (
                distinct_searches("optimization_completed")
                or counts.get("optimization_completed", 0)
            )
            corrected = distinct_searches("interpretation_corrected")
            no_result = distinct_searches("no_convenient_option")
            navigated = distinct_searches("navigation_clicked")
            rank_one = distinct_searches("recommendation_selected", "AND recommendation_rank=1")
            selected_searches = distinct_searches("recommendation_selected")
            alternative_searches = distinct_searches("alternative_selected")
            feedback = {
                row[0]: int(row[1]) for row in connection.execute(
                    "SELECT feedback_value, COUNT(*) FROM analytics_events "
                    "WHERE event_type='feedback_submitted' AND feedback_value IS NOT NULL "
                    "GROUP BY feedback_value"
                )
            }
            reasons = {
                row[0]: int(row[1]) for row in connection.execute(
                    "SELECT feedback_reason, COUNT(*) FROM analytics_events "
                    "WHERE event_type='feedback_submitted' AND feedback_reason IS NOT NULL "
                    "GROUP BY feedback_reason "
                    "ORDER BY COUNT(*) DESC, MIN(occurred_at), feedback_reason"
                )
            }
            median_latency = p95_latency = None
            latency_count = scalar(f"SELECT COUNT(*) {latency_rows}")
            if latency_count:
                middle = (
                    latency_at((latency_count - 1) // 2) + latency_at(latency_count // 2)
                ) / 2
                median_latency = round(middle, 2)
                p95_index = max(
                    0, min(latency_count - 1, int((latency_count - 1) * 0.95 + 0.999999))
                )
                p95_latency = round(latency_at(p95_index), 2)
            active_one_day = scalar(
                f"SELECT COUNT(DISTINCT anonymous_user_id) FROM analytics_events WHERE {day} = ?",
                (today.isoformat(),),
            )
            active_seven_day = scalar(
                f"SELECT COUNT(DISTINCT anonymous_user_id) FROM analytics_events WHERE {day} >= ?",
                (seven_day_cutoff.isoformat(),),
            )
            returning_users = scalar(
                "SELECT COUNT(*) FROM (SELECT anonymous_user_id FROM analytics_events "
                f"GROUP BY anonymous_user_id HAVING COUNT(DISTINCT {day}) >= 2)"
            )
        return AnalyticsReportResponse(
            generated_at=current,
            retention_days=self.retention_days,
            unique_anonymous_users=users,
            searches=searches,
            searches_per_user=round(searches / users, 3) if users else 0,
            completion_rate=round(completions / searches, 4) if searches else 0,
            parse_correction_rate=round(corrected / searches, 4) if searches else 0,
            no_result_rate=round(no_result / searches, 4) if searches else 0,
            rank_one_acceptance_rate=round(rank_one / completions, 4) if completions else 0,
            alternative_selection_rate=(
                round(alternative_searches / selected_searches, 4) if selected_searches else 0
            ),
            navigation_click_rate=round(navigated / completions, 4) if completions else 0,
            positive_feedback=feedback.get("positive", 0),
            negative_feedback=feedback.get("negative", 0),
            common_negative_feedback_reasons=reasons,
            median_optimization_latency_ms=median_latency,
            p95_optimization_latency_ms=p95_latency,
            active_users_one_day=active_one_day,
            active_users_seven_day=active_seven_day,
            returning_users=returning_users,
            return_usage_rate=round(returning_users / users, 4) if users else 0,
            explicit_return_events=counts.get("return_usage", 0),
            event_counts=dict(sorted(counts.items())),
        )
