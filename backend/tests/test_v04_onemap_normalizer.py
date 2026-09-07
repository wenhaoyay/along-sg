from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.providers.base import ProviderInvalidResponseError, ProviderNoRouteError
from app.providers.onemap import OneMapNormalizer


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]


def test_nested_multi_itinerary_fixture_normalizes_times_and_encoded_geometry() -> None:
    result = OneMapNormalizer().normalize_public_transport(
        _fixture("onemap_pt_variant_nested_multi.json")
    )

    assert result.source_schema == "onemap-pt-data.plan-v2"
    assert result.duration_minutes == 30
    assert result.walking_minutes == 5
    assert result.walking_distance_m == 390
    assert result.transfers == 0
    assert result.raw_metadata["itinerary_count"] == 2
    assert result.raw_metadata["selected_itinerary_index"] == 0
    assert result.departure_time is not None
    assert result.arrival_time is not None
    assert result.legs[0].geometry == "encoded-example"
    assert result.legs[0].geometry_format == "encoded_polyline"
    assert "leg.geometry" in result.raw_metadata["nullable_fields"]


def test_nullable_summary_fixture_uses_time_and_walk_leg_fallbacks() -> None:
    result = OneMapNormalizer().normalize_public_transport(
        _fixture("onemap_pt_variant_leg_fallbacks.json")
    )

    assert result.duration_minutes == 20
    assert result.raw_metadata["duration_source"] == "itinerary_time_difference"
    assert result.walking_minutes == 8
    assert result.walking_distance_m == 580
    assert result.raw_metadata["transfer_source"] == "inferred_transit_leg_changes"
    assert result.transfers == 0
    assert result.legs[0].geometry_format == "geojson"


def test_empty_itinerary_list_is_an_explicit_no_route() -> None:
    with pytest.raises(ProviderNoRouteError):
        OneMapNormalizer().normalize_public_transport({"plan": {"itineraries": []}})


def test_malformed_legs_are_an_invalid_response() -> None:
    with pytest.raises(ProviderInvalidResponseError, match="legs"):
        OneMapNormalizer().normalize_public_transport(
            {"plan": {"itineraries": [{"duration": 60, "legs": {}}]}}
        )

