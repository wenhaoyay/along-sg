from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.providers.base import ProviderInvalidResponseError
from app.providers.onemap import OneMapNormalizer


LIVE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "live"
MANIFESTS = sorted(LIVE_ROOT.glob("*/manifest.sanitized.json"))
assert MANIFESTS, "V0.4 live fixtures are required for schema regressions"
LATEST_MANIFEST = MANIFESTS[-1]
MANIFEST = json.loads(LATEST_MANIFEST.read_text(encoding="utf-8"))
ENTRIES = MANIFEST["entries"]
ACCEPTED = [entry for entry in ENTRIES if entry["summary"].get("accepted")]
REJECTED = [entry for entry in ENTRIES if not entry["summary"].get("accepted")]


def _fixture(entry: dict) -> dict:
    return json.loads(
        (LATEST_MANIFEST.parent / entry["fixture"]).read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("entry", ACCEPTED, ids=lambda entry: entry["fixture"][:70])
def test_every_accepted_live_fixture_normalizes_with_verified_units(entry: dict) -> None:
    fixture = _fixture(entry)
    assert fixture["_fixture_meta"]["captured_live"] is True
    assert fixture["_fixture_meta"]["contains_credentials_or_token"] is False
    payload = fixture["response"]
    itinerary = payload["plan"]["itineraries"][0]
    result = OneMapNormalizer().normalize_public_transport(payload)

    elapsed_seconds = (itinerary["endTime"] - itinerary["startTime"]) / 1000
    walk_legs = [leg for leg in itinerary["legs"] if leg["mode"] == "WALK"]
    transit_legs = [leg for leg in itinerary["legs"] if leg["mode"] != "WALK"]

    assert result.duration_minutes == round(elapsed_seconds / 60, 2)
    assert itinerary["duration"] == elapsed_seconds
    assert result.walking_minutes == round(sum(leg["duration"] for leg in walk_legs) / 60, 2)
    walk_leg_distance = sum(leg["distance"] for leg in walk_legs)
    assert itinerary["walkDistance"] == pytest.approx(walk_leg_distance, abs=0.01)
    assert result.walking_distance_m == round(itinerary["walkDistance"], 1)
    assert result.transfers == max(0, len(transit_legs) - 1)
    assert result.departure_time is not None
    assert result.arrival_time is not None
    assert all(len(str(leg["startTime"])) == 13 for leg in itinerary["legs"])
    assert all(
        isinstance(leg["legGeometry"], dict)
        and isinstance(leg["legGeometry"].get("points"), str)
        for leg in itinerary["legs"]
    )


@pytest.mark.parametrize("entry", REJECTED, ids=lambda entry: entry["experiment"])
def test_every_rejected_live_fixture_is_an_invalid_response(entry: dict) -> None:
    fixture = _fixture(entry)
    assert fixture["_fixture_meta"]["response_status"] == 400
    with pytest.raises(ProviderInvalidResponseError):
        OneMapNormalizer().normalize_public_transport(fixture["response"])


def test_live_parameter_contract_regression() -> None:
    by_experiment = {entry["experiment"]: entry for entry in ENTRIES}
    assert by_experiment["minimal"]["summary"]["accepted"] is False
    assert by_experiment["date_time_iso_rejected_expected"]["summary"]["accepted"] is False
    assert by_experiment["date_time_mmddyyyy"]["summary"]["accepted"] is False
    assert by_experiment["date_time_mmddyyyy_mode"]["summary"]["accepted"] is True
    assert by_experiment["time_missing"]["summary"]["accepted"] is False
    assert by_experiment["time_invalid"]["summary"]["accepted"] is False
    assert by_experiment["mode_transit"]["summary"]["accepted"] is True
    assert by_experiment["mode_bus"]["summary"]["accepted"] is True
    assert by_experiment["mode_rail"]["summary"]["accepted"] is True
    assert by_experiment["mode_invalid"]["summary"]["accepted"] is False
    assert by_experiment["max_walk_invalid"]["summary"]["accepted"] is True
    assert by_experiment["itineraries_3"]["summary"]["itinerary_count"] == 1


def test_live_departure_time_changes_waiting_and_total_duration() -> None:
    by_experiment = {entry["experiment"]: entry for entry in ENTRIES}
    morning = by_experiment["departure_morning"]["summary"]["first_itinerary"]
    evening = by_experiment["departure_evening"]["summary"]["first_itinerary"]
    assert morning["duration_raw"] != evening["duration_raw"]
    assert morning["start_time_raw"] != evening["start_time_raw"]
