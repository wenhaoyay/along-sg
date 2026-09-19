from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import HubRepository
from app.main import create_app
from app.poi_taxonomy import CATEGORY_ALIASES
from app.presentation import safe_label
from app.public_data import (
    DATASETS,
    PublicGeoStore,
    ingest_parsed_dataset,
    parse_dataset,
)


def _feature(properties, longitude=103.84, latitude=1.31):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": properties,
    }


def _geojson(*features):
    return json.dumps(
        {"type": "FeatureCollection", "features": list(features)}
    ).encode()


def test_public_data_categories_are_resolvable() -> None:
    assert CATEGORY_ALIASES["hawker centre"] == "hawker_centres"
    assert CATEGORY_ALIASES["fitness corner"] == "fitness"
    assert CATEGORY_ALIASES["public toilet"] == "public_toilets"
    assert CATEGORY_ALIASES["playground"] == "playgrounds"


def test_mrt_exit_parser_keeps_authoritative_exit_identity() -> None:
    parsed = parse_dataset(
        DATASETS["mrt_exits"],
        _geojson(
            _feature(
                {
                    "UNIQUEID": "exit-1",
                    "STATION_NA": "BEAUTY WORLD MRT STATION",
                    "EXIT_CODE": "Exit C",
                }
            )
        ),
    )
    assert parsed.rows_seen == 1
    assert parsed.transport_nodes == [
        {
            "id": "dgov:mrt-exit:exit-1",
            "name": "Beauty World MRT Station Exit C",
            "latitude": 1.31,
            "longitude": 103.84,
            "node_type": "mrt_exit",
            "source": "data.gov.sg:lta-mrt-exits",
            "source_id": "exit-1",
            "last_verified_at": None,
        }
    ]
    assert parsed.geo_features[0]["routeable"] == 0


def test_hawker_parser_creates_routeable_errand_place() -> None:
    parsed = parse_dataset(
        DATASETS["hawker_centres"],
        _geojson(
            _feature(
                {
                    "UNIQUEID": "hawker-1",
                    "NAME": "Test Food Centre",
                    "STATUS": "Existing",
                    "ADDRESS_MYENV": "1 Test Street Singapore 123456",
                    "NUMBER_OF_COOKED_FOOD_STALLS": 42,
                }
            )
        ),
    )
    assert parsed.hubs[0]["source_id"] == "hawker-1"
    assert "data.gov.sg/" in parsed.hubs[0]["name"]
    assert parsed.outlets[0]["categories"] == ("hawker_centres",)
    assert parsed.outlets[0]["search_metadata"] == "42 cooked-food stalls"
    assert parsed.geo_features[0]["routeable"] == 1


def test_park_fitness_area_maps_to_fitness_and_park_facilities() -> None:
    parsed = parse_dataset(
        DATASETS["park_facilities"],
        _geojson(
            _feature(
                {
                    "UNIQUEID": "park-1",
                    "NAME": "Fitness Area",
                    "CLASS": "FITNESS AREA",
                }
            )
        ),
    )
    assert parsed.outlets[0]["categories"] == ("fitness", "park_facilities")
    assert parsed.geo_features[0]["routeable"] == 1


def test_nparks_pcn_label_is_kept_as_park_connector_geometry() -> None:
    raw = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[103.84, 1.31], [103.841, 1.311]],
                    },
                    "properties": {
                        "OBJECTID": 7,
                        "PARK": "Test Connector",
                        "TYPE": "Shared Path",
                        "PARK_TYPE": "PCN",
                    },
                }
            ],
        }
    ).encode()
    parsed = parse_dataset(DATASETS["nparks_tracks"], raw)
    assert parsed.geo_features[0]["layer"] == "park_connectors"


def test_sportsg_rows_are_context_only_when_public_access_is_unknown() -> None:
    raw = (
        "VenueName,PostalCode,Latitude,Longitude,SportsFacility\n"
        "Skyline Residences,123456,1.31,103.84,Fitness Corner\n"
        "Skyline Residences,123456,1.31,103.84,Fitness Corner\n"
    ).encode()
    parsed = parse_dataset(DATASETS["sport_facilities"], raw)
    assert parsed.rows_seen == 2
    assert len(parsed.geo_features) == 1
    assert parsed.geo_features[0]["routeable"] == 0
    properties = json.loads(parsed.geo_features[0]["properties_json"])
    assert properties["_along_access"] == "unknown"
    assert not parsed.hubs
    assert not parsed.outlets


def test_geo_store_replaces_one_source_and_queries_bbox(tmp_path) -> None:
    database = tmp_path / "public.db"
    store = PublicGeoStore(database)
    store.initialize()
    parsed = parse_dataset(
        DATASETS["parks"],
        _geojson(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [103.83, 1.30],
                            [103.85, 1.30],
                            [103.85, 1.32],
                            [103.83, 1.32],
                            [103.83, 1.30],
                        ]
                    ],
                },
                "properties": {"UNIQUEID": "park-a", "NAME": "Test Park"},
            }
        ),
    )
    assert store.replace_source(parsed.spec.source, parsed.geo_features) == 1
    result = store.feature_collection(("parks",), 1.29, 103.82, 1.33, 103.86)
    assert len(result["features"]) == 1
    assert result["features"][0]["properties"]["_along_layer"] == "parks"

    store.replace_source(parsed.spec.source, [])
    assert store.counts_by_layer() == {}


def test_routeable_public_place_uses_nearest_existing_transport_node(tmp_path) -> None:
    database = tmp_path / "along.db"
    repository = HubRepository(database)
    repository.initialize()
    repository.replace_source_data(
        "test-transit",
        [
            {
                "id": "test-node",
                "name": "Test MRT",
                "latitude": 1.3101,
                "longitude": 103.8401,
                "node_type": "station",
                "source": "test-transit",
                "source_id": "node-1",
                "last_verified_at": None,
            }
        ],
        [],
        [],
    )
    parsed = parse_dataset(
        DATASETS["hawker_centres"],
        _geojson(
            _feature(
                {
                    "UNIQUEID": "hawker-near-node",
                    "NAME": "Nearby Food Centre",
                    "STATUS": "Existing",
                }
            )
        ),
    )
    store = PublicGeoStore(database)
    store.initialize()
    ingest_parsed_dataset(repository, store, parsed)

    hubs = repository.find_for_categories(("hawker_centres",))
    imported = next(hub for hub in hubs if hub.source == parsed.spec.source)
    assert imported.transport_area_id == "test-node"
    assert imported.transport_node_distance_m is not None
    assert imported.transport_node_distance_m < 20


def test_transit_linking_checks_adjacent_grid_cells(tmp_path) -> None:
    database = tmp_path / "boundary.db"
    repository = HubRepository(database)
    repository.initialize()
    repository.replace_source_data(
        "boundary-transit",
        [
            {
                "id": "same-cell-far",
                "name": "Far stop",
                "latitude": 1.3101,
                "longitude": 103.84,
                "node_type": "station",
                "source": "boundary-transit",
                "source_id": "far",
                "last_verified_at": None,
            },
            {
                "id": "adjacent-cell-near",
                "name": "Near stop",
                "latitude": 1.32001,
                "longitude": 103.84,
                "node_type": "station",
                "source": "boundary-transit",
                "source_id": "near",
                "last_verified_at": None,
            },
        ],
        [],
        [],
    )
    parsed = parse_dataset(
        DATASETS["hawker_centres"],
        _geojson(
            _feature(
                {
                    "UNIQUEID": "hawker-boundary",
                    "NAME": "Boundary Food Centre",
                    "STATUS": "Existing",
                },
                latitude=1.31999,
            )
        ),
    )
    store = PublicGeoStore(database)
    store.initialize()
    ingest_parsed_dataset(repository, store, parsed)

    imported = next(
        hub
        for hub in repository.find_for_categories(("hawker_centres",))
        if hub.source == parsed.spec.source
    )
    assert imported.transport_area_id == "adjacent-cell-near"
    assert imported.transport_node_distance_m is not None
    assert imported.transport_node_distance_m < 5


def test_source_refresh_does_not_delete_another_non_curated_source(tmp_path) -> None:
    repository = HubRepository(tmp_path / "sources.db")
    repository.initialize()

    def records(source: str):
        hub = {
            "name": "Shared Place",
            "latitude": 1.31,
            "longitude": 103.84,
            "semantic_type": "standalone",
            "transport_area_id": None,
            "consolidation_group_id": source,
            "source": source,
            "source_id": f"{source}-hub",
            "last_verified_at": None,
            "opening_hours": None,
            "closure_status": "unknown",
            "transport_node_distance_m": 100,
            "address": None,
        }
        outlet = {
            "hub_source_id": f"{source}-hub",
            "name": f"{source} outlet",
            "brand_slug": None,
            "categories": ("convenience",),
            "source": source,
            "source_id": f"{source}-outlet",
            "last_verified_at": None,
            "opening_hours": None,
            "closure_status": "unknown",
        }
        return hub, outlet

    first_hub, first_outlet = records("source-one")
    repository.replace_source_data("source-one", [], [first_hub], [first_outlet])

    second_hub, second_outlet = records("source-two")
    second_hub["name"] = "Shared-Place"
    repository.replace_source_data("source-two", [], [second_hub], [second_outlet])

    assert any(
        hub.source == "source-one"
        for hub in repository.find_for_categories(("convenience",))
    )


def test_data_gov_internal_identity_never_reaches_display() -> None:
    assert (
        safe_label(
            "Test Food Centre · data.gov.sg/d_4a086da0a5553be1d89383cd90d07ecd:hawker-1"
        )
        == "Test Food Centre"
    )


def test_public_layers_endpoint_is_bbox_bounded(tmp_path) -> None:
    database = tmp_path / "api.db"
    repository = HubRepository(database)
    repository.initialize()
    store = PublicGeoStore(database)
    store.initialize()
    parsed = parse_dataset(
        DATASETS["parks"],
        _geojson(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [103.83, 1.30],
                            [103.85, 1.30],
                            [103.85, 1.32],
                            [103.83, 1.32],
                            [103.83, 1.30],
                        ]
                    ],
                },
                "properties": {"UNIQUEID": "park-api", "NAME": "API Park"},
            }
        ),
    )
    store.replace_source(parsed.spec.source, parsed.geo_features)

    app = create_app(
        Settings(
            onemap_mock=True,
            database_path=database,
            analytics_database_path=tmp_path / "analytics.db",
        )
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/public-layers",
            params={
                "min_lat": 1.29,
                "min_lon": 103.82,
                "max_lat": 1.33,
                "max_lon": 103.86,
                "layers": "parks",
            },
        )
        invalid = client.get(
            "/api/public-layers",
            params={
                "min_lat": 1.33,
                "min_lon": 103.82,
                "max_lat": 1.29,
                "max_lon": 103.86,
            },
        )
    assert response.status_code == 200
    assert response.json()["features"][0]["properties"]["_along_layer"] == "parks"
    assert invalid.status_code == 422
