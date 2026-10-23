"""Coverage and pruning regressions for the V0.7.6 transit-graph work.

Three defects motivated these tests, each of which silently degraded results
rather than raising:

1. Overpass honours only the last geometry modifier, so `out center tags bb`
   returned `bounds` and no `center`. Every way and relation was discarded,
   which meant 244 of 250 malls - a mall is a building polygon, not a point.
2. The capture asked only for rail stations, so the transit-proximity filter
   scored the catalog against ~130 nodes and rejected 46% of hubs as
   unreachable. Singapore has roughly 5,100 bus stops.
3. Candidates were truncated to the routing budget by great-circle distance
   from the origin-destination chord, which nothing travels along.
"""

from __future__ import annotations

import random

import pytest

from app.domain import CandidateOption, Coordinate, Hub
from app.poi_ingestion import (
    RAIL_NODE_TYPES,
    _coordinate,
    _is_station_area,
    _SpatialIndex,
    transform_osm_payload,
)
from app.providers.mock import haversine_km
from app.services.candidates import prune_candidates, transit_access_rank_km


def _hub(hub_id: int, latitude: float, longitude: float, transport_node_distance_m: float | None) -> Hub:
    return Hub(
        id=hub_id,
        name=f"Hub {hub_id}",
        coordinate=Coordinate(latitude, longitude),
        stores=(),
        transport_node_distance_m=transport_node_distance_m,
    )


def _option(hub: Hub, straight_line_detour_km: float) -> CandidateOption:
    return CandidateOption(
        stops=(hub,),
        required_categories=("groceries",),
        consolidated=False,
        straight_line_detour_km=straight_line_detour_km,
    )


def test_polygon_mapped_places_keep_a_coordinate_from_bounds() -> None:
    """A way with bounds but no center must not be discarded."""
    element = {
        "type": "way", "id": 7,
        "bounds": {"minlat": 1.300, "maxlat": 1.310, "minlon": 103.800, "maxlon": 103.820},
        "tags": {"shop": "mall", "name": "Polygon Mall"},
    }
    coordinate = _coordinate(element)
    assert coordinate is not None
    assert coordinate.latitude == pytest.approx(1.305)
    assert coordinate.longitude == pytest.approx(103.810)
    # An explicit center still wins over the bounds midpoint.
    assert _coordinate({**element, "center": {"lat": 1.4, "lon": 103.9}}).latitude == pytest.approx(1.4)
    assert _coordinate({"type": "way", "id": 8, "tags": {}}) is None


def test_mall_polygons_survive_ingestion_and_absorb_their_outlets() -> None:
    payload = {
        "capture_metadata": {"captured_at": "2026-09-09T00:00:00+00:00"},
        "elements": [
            {
                "type": "way", "id": 1,
                "bounds": {"minlat": 1.299, "maxlat": 1.301, "minlon": 103.799, "maxlon": 103.801},
                "tags": {"shop": "mall", "name": "Bounds Only Mall"},
            },
            {
                "type": "node", "id": 2, "lat": 1.300, "lon": 103.800,
                "tags": {"shop": "supermarket", "name": "Cold Storage"},
            },
        ],
    }
    _nodes, hubs, outlets, report = transform_osm_payload(payload)
    assert report.imported_malls == 1
    malls = [hub for hub in hubs if hub["semantic_type"] == "mall"]
    assert [hub["name"] for hub in malls] == ["Bounds Only Mall"]
    # The supermarket sits inside the polygon, so it consolidates into the mall
    # rather than spawning a standalone hub of its own.
    assert len(outlets) == 1
    assert outlets[0]["hub_source_id"] == malls[0]["source_id"]
    assert not [hub for hub in hubs if hub["semantic_type"] == "standalone"]


def test_bus_stops_become_transit_nodes_without_becoming_station_areas() -> None:
    payload = {
        "capture_metadata": {"captured_at": "2026-09-09T00:00:00+00:00"},
        "elements": [
            {"type": "node", "id": 1, "lat": 1.3000, "lon": 103.8000,
             "tags": {"highway": "bus_stop", "name": "Opp Blk 123"}},
            {"type": "node", "id": 2, "lat": 1.3500, "lon": 103.8500,
             "tags": {"railway": "station", "name": "Somewhere MRT"}},
            # Beside the bus stop, far from any rail.
            {"type": "node", "id": 3, "lat": 1.30005, "lon": 103.80005,
             "tags": {"shop": "convenience", "name": "Cheers"}},
            # Beside the rail station.
            {"type": "node", "id": 4, "lat": 1.35005, "lon": 103.85005,
             "tags": {"shop": "convenience", "name": "7-Eleven"}},
        ],
    }
    nodes, hubs, _outlets, report = transform_osm_payload(payload)

    assert report.imported_transport_nodes == 2
    assert {node["node_type"] for node in nodes} == {"bus_stop", "station"}

    by_name = {hub["name"]: hub for hub in hubs}
    # Both are reachable, so both keep a transit node and a short distance.
    assert by_name["Cheers"]["transport_node_distance_m"] < 50
    assert by_name["7-Eleven"]["transport_node_distance_m"] < 50
    # Only the rail-adjacent one is a station area. A bus stop is not a station.
    assert by_name["Cheers"]["semantic_type"] == "standalone"
    assert by_name["7-Eleven"]["semantic_type"] == "station_area"


def test_station_area_needs_rail_within_150m() -> None:
    assert _is_station_area(0.0) is True
    assert _is_station_area(150.0) is True
    assert _is_station_area(150.1) is False
    assert _is_station_area(None) is False
    assert "station" in RAIL_NODE_TYPES
    assert "bus_stop" not in RAIL_NODE_TYPES


def test_spatial_index_agrees_with_an_exhaustive_scan() -> None:
    """The bucketed lookup is an optimisation, not an approximation."""
    generator = random.Random(20260909)
    entries = [
        (
            f"node/{index}",
            Coordinate(
                1.20 + generator.random() * 0.28,
                103.62 + generator.random() * 0.42,
            ),
        )
        for index in range(2000)
    ]
    index = _SpatialIndex(entries)
    for _ in range(60):
        probe = Coordinate(1.20 + generator.random() * 0.28, 103.62 + generator.random() * 0.42)
        expected = min(entries, key=lambda item: haversine_km(probe, item[1]))
        node_id, distance_m = index.nearest(probe)
        assert node_id == expected[0]
        assert distance_m == round(haversine_km(probe, expected[1]) * 1000, 1)

    assert _SpatialIndex([]).nearest(Coordinate(1.3, 103.8)) == (None, None)


def test_pruning_prefers_the_on_route_transit_served_stop_over_the_closer_chord() -> None:
    """The stop nearest the straight line is not the stop cheapest to reach.

    `on_route` sits on the baseline polyline beside a transit node. `off_route`
    is closer to the origin-destination chord but 900 m from anything you can
    board. Ranking by chord distance picks `off_route` and wastes the single
    routing slot on it.
    """
    origin = Coordinate(1.4052, 103.9024)
    destination = Coordinate(1.3043, 103.8322)
    geometry = (origin, Coordinate(1.3600, 103.8500), destination)

    on_route = _hub(1, 1.3600, 103.8500, transport_node_distance_m=40.0)
    off_route = _hub(2, 1.3548, 103.8673, transport_node_distance_m=900.0)

    options = [_option(off_route, 0.4), _option(on_route, 1.2)]

    chord_ranked = prune_candidates(options, origin, destination, max_candidates=1, max_detour_km=50)
    assert chord_ranked[0].stops[0].id == off_route.id

    transit_ranked = prune_candidates(
        options, origin, destination, max_candidates=1, max_detour_km=50, geometry=geometry,
    )
    assert transit_ranked[0].stops[0].id == on_route.id


def test_transit_rank_charges_for_leaving_the_route_and_for_the_access_walk() -> None:
    geometry = (Coordinate(1.30, 103.80), Coordinate(1.30, 103.90))
    on_route = _option(_hub(1, 1.30, 103.85, transport_node_distance_m=0.0), 0.0)
    assert transit_access_rank_km(on_route, geometry) == 0.0

    # 500 m of access walk, still on the route.
    access_only = _option(_hub(2, 1.30, 103.85, transport_node_distance_m=500.0), 0.0)
    assert transit_access_rank_km(access_only, geometry) == pytest.approx(0.5)

    # Off the route is charged both ways.
    off_route = _option(_hub(3, 1.30, 103.85, transport_node_distance_m=None), 0.0)
    off_route.stops[0].__dict__["coordinate"] = Coordinate(1.31, 103.85)
    assert transit_access_rank_km(off_route, geometry) > 2.0

    # With no geometry the proxy abstains rather than inventing an order.
    assert transit_access_rank_km(on_route, ()) == 0.0


def test_missing_transit_distance_does_not_crash_the_rank() -> None:
    geometry = (Coordinate(1.30, 103.80), Coordinate(1.30, 103.90))
    unknown = _option(_hub(1, 1.30, 103.85, transport_node_distance_m=None), 0.0)
    assert transit_access_rank_km(unknown, geometry) == 0.0


def test_incoming_hub_supersedes_the_curated_seed_for_the_same_building(tmp_path) -> None:
    """One mall must not reach the user as two competing recommendations."""
    import sqlite3

    from app.db import HubRepository

    database = tmp_path / "errands.db"
    repository = HubRepository(database)
    repository.initialize()

    def ion_hubs() -> list[tuple[str, str]]:
        with sqlite3.connect(database) as connection:
            return [
                (row[0], row[1]) for row in connection.execute(
                    "SELECT name, source FROM hubs WHERE name LIKE 'ION Orchard%' ORDER BY name"
                )
            ]

    assert ion_hubs() == [("ION Orchard", "curated")], "seed should bootstrap the mall"

    repository.replace_source_data(
        "openstreetmap",
        transport_nodes=[],
        hubs=[{
            "name": "ION Orchard", "latitude": 1.3041, "longitude": 103.8319,
            "semantic_type": "mall", "transport_area_id": None,
            "consolidation_group_id": "mall:way/1", "source": "openstreetmap",
            "source_id": "mall:way/1", "last_verified_at": None,
            "opening_hours": None, "closure_status": "unknown",
            "transport_node_distance_m": 40.0, "address": None,
        }],
        outlets=[],
    )
    # The curated copy is retired, and the surviving hub keeps the plain name -
    # no "ION Orchard - mall:way/1" collision suffix.
    assert ion_hubs() == [("ION Orchard", "openstreetmap")]


def test_prefixed_source_ids_are_stripped_from_display_names() -> None:
    from app.presentation import safe_label

    assert safe_label("ION Orchard · mall:way/231917869") == "ION Orchard"
    assert safe_label("Bencoolen Underground Mall · mall:node/4233370770") == (
        "Bencoolen Underground Mall"
    )
    # The pre-existing unprefixed form still works.
    assert safe_label("Hawker Centre · node/10283940109") == "Hawker Centre"
    assert safe_label("Convenience node/55") == "Convenience"
    # A legitimate name is untouched.
    assert safe_label("Plaza Singapura") == "Plaza Singapura"


def test_startup_reseeding_survives_a_superseded_seed_hub(tmp_path) -> None:
    """Re-seeding must not collide with the row that replaced it.

    `initialize()` runs on every startup. Once ingestion supersedes a curated
    mall, that name belongs to the ingested hub, and re-inserting the seed row
    raised UNIQUE(hubs.name) - which failed lifespan startup and exited the
    server, not just the request.
    """
    import sqlite3

    from app.db import HubRepository

    database = tmp_path / "errands.db"
    repository = HubRepository(database)
    repository.initialize()
    repository.replace_source_data(
        "openstreetmap",
        transport_nodes=[],
        hubs=[{
            "name": "ION Orchard", "latitude": 1.3041, "longitude": 103.8319,
            "semantic_type": "mall", "transport_area_id": None,
            "consolidation_group_id": "mall:way/1", "source": "openstreetmap",
            "source_id": "mall:way/1", "last_verified_at": None,
            "opening_hours": None, "closure_status": "unknown",
            "transport_node_distance_m": 40.0, "address": None,
        }],
        outlets=[],
    )

    # Restart twice: idempotence matters as much as the first success.
    HubRepository(database).initialize()
    HubRepository(database).initialize()

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT name, source FROM hubs WHERE name='ION Orchard'"
        ).fetchall()
    assert rows == [("ION Orchard", "openstreetmap")]
