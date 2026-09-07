"""Bounded live OneMap PT contract probe.

The script is intentionally independent of the production normalizer. It authenticates only
when backend credentials are present, tests the request contract, then captures representative
sanitised responses. Authentication responses and headers are never persisted.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
BASE_URL = os.getenv("ONEMAP_BASE_URL", "https://www.onemap.gov.sg").rstrip("/")
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "live"
SINGAPORE_TZ = ZoneInfo("Asia/Singapore")
REQUEST_BUDGET = 24

REFERENCE = {
    "name": "contract_reference_punggol_to_orchard",
    "start": "1.4052,103.9024",
    "end": "1.3043,103.8322",
}

JOURNEYS = (
    {
        "name": "mrt_focused_jurong_east_to_raffles_place",
        "expected_coverage": "MRT-focused",
        "start": "1.3331,103.7422",
        "end": "1.2840,103.8515",
    },
    {
        "name": "bus_only_where_possible_nus_to_holland_village",
        "expected_coverage": "bus-only where the router permits",
        "start": "1.3038,103.7740",
        "end": "1.3115,103.7966",
    },
    {
        "name": "bus_mrt_punggol_to_nus",
        "expected_coverage": "bus plus MRT",
        "start": "1.4052,103.9024",
        "end": "1.2966,103.7764",
    },
    {
        "name": "transfer_heavy_woodlands_to_harbourfront",
        "expected_coverage": "multiple transit legs",
        "start": "1.4360,103.7865",
        "end": "1.2653,103.8215",
    },
    {
        "name": "long_distance_changi_airport_to_tuas_link",
        "expected_coverage": "long-distance cross-island",
        "start": "1.3571,103.9887",
        "end": "1.3404,103.6368",
    },
)


def sanitise(value: Any, key: str = "") -> Any:
    lowered = key.casefold()
    if any(secret in lowered for secret in ("token", "password", "email", "authorization")):
        return "<redacted>"
    if isinstance(value, dict):
        return {name: sanitise(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [sanitise(item, key) for item in value]
    return value


def response_summary(payload: Any, status_code: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "http_status": status_code,
        "json_object": isinstance(payload, dict),
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "accepted": status_code < 400,
    }
    if not isinstance(payload, dict):
        summary["accepted"] = False
        return summary
    if payload.get("error"):
        summary["accepted"] = False
        summary["error_present"] = True
    plan = payload.get("plan")
    if not isinstance(plan, dict) and isinstance(payload.get("data"), dict):
        plan = payload["data"].get("plan")
    itineraries = plan.get("itineraries") if isinstance(plan, dict) else None
    if isinstance(itineraries, list):
        summary["itinerary_count"] = len(itineraries)
        summary["accepted"] = summary["accepted"] and bool(itineraries)
        if itineraries and isinstance(itineraries[0], dict):
            first = itineraries[0]
            summary["first_itinerary"] = {
                "duration_raw": first.get("duration"),
                "walk_time_raw": first.get("walkTime"),
                "walk_distance_raw": first.get("walkDistance"),
                "transfer_raw": first.get("transfers", first.get("numTransfers")),
                "start_time_raw": first.get("startTime", first.get("departureTime")),
                "end_time_raw": first.get("endTime", first.get("arrivalTime")),
                "leg_modes": [
                    leg.get("mode")
                    for leg in first.get("legs", [])
                    if isinstance(leg, dict)
                ],
                "geometry_value_types": sorted(
                    {
                        type(leg.get("legGeometry", leg.get("geometry"))).__name__
                        for leg in first.get("legs", [])
                        if isinstance(leg, dict)
                        and leg.get("legGeometry", leg.get("geometry")) is not None
                    }
                ),
            }
    return summary


def safe_filename(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def main() -> int:
    email = os.getenv("ONEMAP_EMAIL") or os.getenv("ONEMAP_API_EMAIL")
    password = os.getenv("ONEMAP_PASSWORD") or os.getenv("ONEMAP_API_PASSWORD")
    if not email or not password:
        print(
            "Skipped: set backend-only ONEMAP_EMAIL and ONEMAP_PASSWORD "
            "to run the bounded live PT probe."
        )
        return 2

    captured_at = datetime.now(SINGAPORE_TZ)
    capture_dir = OUTPUT_ROOT / captured_at.strftime("%Y-%m-%dT%H%M%S")
    capture_dir.mkdir(parents=True, exist_ok=True)
    request_count = 0
    manifest_entries: list[dict[str, Any]] = []

    with httpx.Client(timeout=20.0) as client:
        auth = client.post(
            f"{BASE_URL}/api/auth/post/getToken",
            json={"email": email, "password": password},
        )
        auth.raise_for_status()
        auth_payload = auth.json()
        token = auth_payload.get("access_token")
        if not token:
            raise RuntimeError("OneMap authentication returned no access token")

        def capture(
            scenario: dict[str, str],
            experiment: str,
            params: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal request_count
            if request_count >= REQUEST_BUDGET:
                raise RuntimeError(
                    f"Probe request budget of {REQUEST_BUDGET} would be exceeded"
                )
            request_count += 1
            started = time.perf_counter()
            try:
                response = client.get(
                    f"{BASE_URL}/api/public/routingsvc/route",
                    params=params,
                    headers={"Authorization": token},
                )
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                try:
                    payload: Any = response.json()
                except ValueError:
                    payload = {"_non_json_body": response.text[:500]}
                summary = response_summary(payload, response.status_code)
            except httpx.TimeoutException:
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                payload = {"_probe_error": "timeout"}
                summary = {
                    "accepted": False,
                    "probe_error": "timeout",
                    "http_status": None,
                }

            fixture = {
                "_fixture_meta": {
                    "captured_live": True,
                    "captured_at": captured_at.isoformat(),
                    "scenario": scenario["name"],
                    "expected_coverage": scenario.get("expected_coverage"),
                    "experiment": experiment,
                    "request": sanitise(params),
                    "response_status": summary.get("http_status"),
                    "provider_latency_ms": latency_ms,
                    "contains_credentials_or_token": False,
                },
                "response": sanitise(payload),
            }
            filename = (
                f"{request_count:02d}__{safe_filename(scenario['name'])}"
                f"__{safe_filename(experiment)}.sanitized.json"
            )
            (capture_dir / filename).write_text(
                json.dumps(fixture, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            entry = {
                "fixture": filename,
                "scenario": scenario["name"],
                "experiment": experiment,
                "request": sanitise(params),
                "latency_ms": latency_ms,
                "summary": summary,
            }
            manifest_entries.append(entry)
            return entry

        route_base = {
            "start": REFERENCE["start"],
            "end": REFERENCE["end"],
            "routeType": "pt",
        }
        now = captured_at.replace(second=0, microsecond=0)
        contract_candidates = (
            ("minimal", route_base),
            (
                "date_time_iso_rejected_expected",
                {
                    **route_base,
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                },
            ),
            (
                "date_time_mmddyyyy",
                {
                    **route_base,
                    "date": now.strftime("%m-%d-%Y"),
                    "time": now.strftime("%H:%M:%S"),
                },
            ),
            (
                "date_time_mmddyyyy_mode",
                {
                    **route_base,
                    "date": now.strftime("%m-%d-%Y"),
                    "time": now.strftime("%H:%M:%S"),
                    "mode": "TRANSIT",
                },
            ),
            (
                "historical_full_contract",
                {
                    **route_base,
                    "date": now.strftime("%m-%d-%Y"),
                    "time": now.strftime("%H:%M:%S"),
                    "mode": "TRANSIT",
                    "maxWalkDistance": 1000,
                    "numItineraries": 1,
                },
            ),
        )
        accepted_base: dict[str, Any] | None = None
        for experiment, params in contract_candidates:
            entry = capture(REFERENCE, experiment, dict(params))
            if entry["summary"].get("accepted"):
                accepted_base = dict(params)

        if accepted_base is None:
            print(
                f"No accepted PT contract found. Inspect fixtures in {capture_dir}; "
                f"{request_count} bounded requests made."
            )
            return 3

        morning = (now + timedelta(days=1)).replace(hour=8, minute=0)
        evening = morning.replace(hour=18)
        parameter_experiments = (
            (
                "departure_morning",
                {
                    **accepted_base,
                    "date": morning.strftime("%m-%d-%Y"),
                    "time": morning.strftime("%H:%M:%S"),
                },
            ),
            (
                "departure_evening",
                {
                    **accepted_base,
                    "date": evening.strftime("%m-%d-%Y"),
                    "time": evening.strftime("%H:%M:%S"),
                },
            ),
            ("mode_transit", {**accepted_base, "mode": "TRANSIT"}),
            ("mode_bus", {**accepted_base, "mode": "BUS"}),
            ("mode_rail", {**accepted_base, "mode": "RAIL"}),
            ("mode_invalid", {**accepted_base, "mode": "NOT_A_MODE"}),
            ("max_walk_250", {**accepted_base, "maxWalkDistance": 250}),
            ("max_walk_2000", {**accepted_base, "maxWalkDistance": 2000}),
            ("max_walk_invalid", {**accepted_base, "maxWalkDistance": -1}),
            ("itineraries_1", {**accepted_base, "numItineraries": 1}),
            ("itineraries_3", {**accepted_base, "numItineraries": 3}),
            (
                "time_missing",
                {key: value for key, value in accepted_base.items() if key != "time"},
            ),
            ("time_invalid", {**accepted_base, "time": "not-a-time"}),
            ("date_invalid", {**accepted_base, "date": "not-a-date"}),
        )
        for experiment, params in parameter_experiments:
            capture(REFERENCE, experiment, params)

        representative_params = {
            **accepted_base,
            "date": morning.strftime("%m-%d-%Y"),
            "time": morning.strftime("%H:%M:%S"),
        }
        for journey in JOURNEYS:
            capture(
                journey,
                "representative_route",
                {
                    **representative_params,
                    "start": journey["start"],
                    "end": journey["end"],
                },
            )

    manifest = {
        "_fixture_meta": {
            "captured_live": True,
            "captured_at": captured_at.isoformat(),
            "request_budget": REQUEST_BUDGET,
            "request_count": request_count,
            "credentials_or_tokens_persisted": False,
        },
        "entries": manifest_entries,
    }
    manifest_path = capture_dir / "manifest.sanitized.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        f"Captured {request_count} bounded live requests in {capture_dir}. "
        f"Manifest: {manifest_path.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
