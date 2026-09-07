from __future__ import annotations

from scripts.probe_onemap_pt import JOURNEYS, REQUEST_BUDGET, sanitise


def test_probe_sanitiser_removes_nested_credentials_and_tokens() -> None:
    raw = {
        "access_token": "secret",
        "nested": {
            "email": "person@example.test",
            "password": "secret",
            "Authorization": "Bearer secret",
        },
        "plan": {"geometry": "public-route-shape"},
    }

    cleaned = sanitise(raw)

    assert cleaned["access_token"] == "<redacted>"
    assert set(cleaned["nested"].values()) == {"<redacted>"}
    assert cleaned["plan"]["geometry"] == "public-route-shape"


def test_probe_matrix_is_representative_and_hard_bounded() -> None:
    coverage = {journey["expected_coverage"] for journey in JOURNEYS}
    assert len(JOURNEYS) == 5
    assert "MRT-focused" in coverage
    assert "bus-only where the router permits" in coverage
    assert "bus plus MRT" in coverage
    assert "multiple transit legs" in coverage
    assert "long-distance cross-island" in coverage
    assert REQUEST_BUDGET == 24
