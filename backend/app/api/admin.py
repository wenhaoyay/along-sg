"""Beta analytics events and the token-gated operator reports.

Analytics is off unless ANALYTICS_ENABLED=true (see app.ops). While off there is
no store, and both analytics routes answer 404 as if they did not exist.
"""

from __future__ import annotations

import asyncio
import hmac
import logging

from fastapi import FastAPI, HTTPException, Request

from app.analytics import AnalyticsRepository
from app.config import Settings
from app.schemas import (
    AnalyticsEventRequest,
    AnalyticsEventResponse,
    AnalyticsReportResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx's INFO request line includes the full URL. Some upstream APIs require
# credentials in query parameters, so never allow that logger to emit at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)


def register(app: FastAPI, app_settings: Settings) -> None:
    @app.post("/api/analytics/events", response_model=AnalyticsEventResponse)
    async def record_analytics(payload: AnalyticsEventRequest, request: Request):
        analytics: AnalyticsRepository | None = request.app.state.analytics
        if analytics is None:
            raise HTTPException(status_code=404, detail="Not found")
        return AnalyticsEventResponse(accepted=await asyncio.to_thread(analytics.record, payload))

    @app.get("/api/admin/analytics", response_model=AnalyticsReportResponse)
    async def analytics_report(request: Request):
        expected = app_settings.beta_admin_token
        analytics: AnalyticsRepository | None = request.app.state.analytics
        if not expected or analytics is None:
            raise HTTPException(status_code=404, detail="Not found")
        authorization = request.headers.get("authorization", "")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid admin token")
        return await asyncio.to_thread(analytics.report)

    @app.get("/api/admin/discovery-gaps")
    async def discovery_gap_report(request: Request):
        expected = app_settings.beta_admin_token
        if not expected or not app_settings.discovery_gap_telemetry_enabled:
            raise HTTPException(status_code=404, detail="Not found")
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid admin token")
        return request.app.state.need_resolver.metrics_snapshot()
