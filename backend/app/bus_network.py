"""The static bus network: stops, and which services call at them when.

Live arrivals answer "when is the next 95". This answers the question that has
to be asked first - "is the 95 running at all right now" - which is what lets
the app tell "nothing due" apart from "not in operation" instead of showing one
phrase for both. LTA's own front-end advisement names those as distinct states
and says the second needs the Bus Routes dataset.

It also gives the transit graph authoritative identity. The graph currently
comes from OpenStreetMap, whose bus stops carry no stop code at all, so nothing
in the database can be joined to an arrival. LTA's stops carry the code that
OneMap also returns on every bus leg.

Field names are LTA's, from the API User Guide v6.9 sections 2.3 and 2.4:
BusRoutes uses `WD_FirstBus` / `SAT_LastBus` / `SUN_FirstBus` and friends. Note
these are not the names some third-party bindings use; they were read off the
guide rather than inferred.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

# Services that do not run on a given day come back as a dash, an empty string,
# or absent. All three mean the same thing and none of them is a time.
_NO_SERVICE = {"", "-", "0000-0000", "none"}


def _coordinate(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # LTA publishes a handful of stops at the null island; they are placeholders
    # rather than locations off the coast of Africa.
    return None if number == 0.0 else number


def transform_bus_stops(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """BusStops rows into storable records, dropping anything unusable."""
    rows: dict[str, dict[str, Any]] = {}
    for element in elements:
        if not isinstance(element, dict):
            continue
        code = str(element.get("BusStopCode") or "").strip()
        if not (len(code) == 5 and code.isdigit()):
            continue
        latitude = _coordinate(element.get("Latitude"))
        longitude = _coordinate(element.get("Longitude"))
        if latitude is None or longitude is None:
            continue
        # Later pages win, so a re-request that overlaps is harmless.
        rows[code] = {
            "stop_code": code,
            "road_name": str(element.get("RoadName") or "").strip() or None,
            "description": str(element.get("Description") or "").strip() or None,
            "latitude": latitude,
            "longitude": longitude,
        }
    return list(rows.values())


def _clock(value: Any) -> str | None:
    """LTA publishes HHMM as a string: "0620", "2352", sometimes "2400".

    Returns a normalised HHMM, or None when the service does not run. "2400"
    is a real value meaning midnight at the end of the day, and rejecting it
    would silently mark those services as never running.
    """
    text = str(value or "").strip()
    if text.lower() in _NO_SERVICE:
        return None
    if not (len(text) == 4 and text.isdigit()):
        return None
    hour, minute = int(text[:2]), int(text[2:])
    if hour == 24 and minute == 0:
        return "2400"
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}{minute:02d}"


def transform_bus_routes(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[tuple[str, int, int], dict[str, Any]] = {}
    for element in elements:
        if not isinstance(element, dict):
            continue
        service = str(element.get("ServiceNo") or "").strip()
        code = str(element.get("BusStopCode") or "").strip()
        if not service or not (len(code) == 5 and code.isdigit()):
            continue
        try:
            direction = int(element.get("Direction", 1))
            sequence = int(element.get("StopSequence", 0))
        except (TypeError, ValueError):
            continue
        try:
            distance = float(element.get("Distance"))
        except (TypeError, ValueError):
            distance = None
        rows[(service, direction, sequence)] = {
            "service_no": service,
            "direction": direction,
            "stop_sequence": sequence,
            "stop_code": code,
            "operator": str(element.get("Operator") or "").strip() or None,
            "distance_km": distance,
            "weekday_first": _clock(element.get("WD_FirstBus")),
            "weekday_last": _clock(element.get("WD_LastBus")),
            "saturday_first": _clock(element.get("SAT_FirstBus")),
            "saturday_last": _clock(element.get("SAT_LastBus")),
            "sunday_first": _clock(element.get("SUN_FirstBus")),
            "sunday_last": _clock(element.get("SUN_LastBus")),
        }
    return list(rows.values())


def window_for(row: dict[str, Any], moment: datetime) -> tuple[str | None, str | None]:
    """The first and last bus applying on the day of `moment`.

    Saturday and Sunday are published separately, and public holidays follow the
    Sunday timetable in practice - which this does not attempt to know, because
    guessing a holiday calendar would be a worse error than using the weekday
    one.
    """
    weekday = moment.weekday()
    if weekday == 5:
        return row.get("saturday_first"), row.get("saturday_last")
    if weekday == 6:
        return row.get("sunday_first"), row.get("sunday_last")
    return row.get("weekday_first"), row.get("weekday_last")


def _minutes(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[2:])


def is_in_operation(row: dict[str, Any], moment: datetime) -> bool | None:
    """Whether this service is scheduled to call at this stop right now.

    None means "cannot say" - no published window - which the caller must not
    collapse into False. Claiming a service has stopped running when the data
    is simply absent is the mistake this whole distinction exists to avoid.

    A last bus after midnight is published as a smaller number than the first
    ("0015" against "0530"), so the window wraps and the comparison has to.
    """
    first, last = window_for(row, moment)
    if not first or not last:
        return None
    now = moment.hour * 60 + moment.minute
    start, end = _minutes(first), _minutes(last)
    if start == end:
        return None
    if start < end:
        return start <= now <= end
    # Wraps past midnight: in service from the first bus to the end of the day,
    # and again from the start of the day to the last bus.
    return now >= start or now <= end


def stop_display_name(row: dict[str, Any]) -> str:
    """What LTA calls the stop, in the order a person would say it.

    The description is the landmark and is what OneMap shows on a leg; the road
    name disambiguates the several stops that share one.
    """
    description = (row.get("description") or "").strip()
    road = (row.get("road_name") or "").strip()
    if description and road:
        return f"{description}, {road}"
    return description or road or str(row.get("stop_code") or "")


def operating_hours_text(row: dict[str, Any], moment: datetime) -> str | None:
    """"First bus 05:30, last bus 23:52", or nothing if unpublished."""
    first, last = window_for(row, moment)
    if not first or not last:
        return None
    return f"First bus {_pretty(first)}, last bus {_pretty(last)}"


def _pretty(clock: str) -> str:
    if clock == "2400":
        return "midnight"
    return time(int(clock[:2]), int(clock[2:])).strftime("%H:%M")
