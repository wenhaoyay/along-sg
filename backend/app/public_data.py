from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx

from app.db import HubRepository
from app.poi_taxonomy import normalize_text


DATA_GOV_SG_API = "https://api-open.data.gov.sg/v1/public/api/datasets"
OPEN_DATA_LICENCE_URL = "https://data.gov.sg/open-data-licence"
SINGAPORE_TZ = ZoneInfo("Asia/Singapore")


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    dataset_id: str
    source: str
    layer: str
    file_format: str
    routeable: bool = False


DATASETS: dict[str, DatasetSpec] = {
    "mrt_exits": DatasetSpec(
        "mrt_exits",
        "d_b39d3a0871985372d7e1637193335da5",
        "data.gov.sg:lta-mrt-exits",
        "mrt_exits",
        "geojson",
    ),
    "hawker_centres": DatasetSpec(
        "hawker_centres",
        "d_4a086da0a5553be1d89383cd90d07ecd",
        "data.gov.sg:nea-hawker-centres",
        "hawker_centres",
        "geojson",
        True,
    ),
    "sport_facilities": DatasetSpec(
        "sport_facilities",
        "d_2cfb0867cdeb2b7303068995699dc33b",
        "data.gov.sg:sportsg-facilities",
        "sport_facilities",
        "csv",
        False,
    ),
    "park_facilities": DatasetSpec(
        "park_facilities",
        "d_14d807e20158338fd578c2913953516e",
        "data.gov.sg:nparks-facilities",
        "park_facilities",
        "geojson",
        True,
    ),
    "parks": DatasetSpec(
        "parks",
        "d_77d7ec97be83d44f61b85454f844382f",
        "data.gov.sg:nparks-parks",
        "parks",
        "geojson",
        False,
    ),
    "nparks_tracks": DatasetSpec(
        "nparks_tracks",
        "d_306cc1018cb733346681883ee6d73054",
        "data.gov.sg:nparks-tracks",
        "nparks_tracks",
        "geojson",
        False,
    ),
}


@dataclass
class ParsedDataset:
    spec: DatasetSpec
    transport_nodes: list[dict[str, Any]]
    hubs: list[dict[str, Any]]
    outlets: list[dict[str, Any]]
    geo_features: list[dict[str, Any]]
    rows_seen: int
    skipped: int = 0


@dataclass(frozen=True)
class PublicDataIngestionReport:
    key: str
    dataset_id: str
    rows_seen: int
    transport_nodes: int
    hubs: int
    outlets: int
    geo_features: int
    skipped: int


class DataGovSgClient:
    """Small downloader for data.gov.sg's public dataset download API."""

    def __init__(self, client: httpx.AsyncClient | None = None, timeout_seconds: float = 45.0):
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def download(self, spec: DatasetSpec) -> bytes:
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout_seconds)
        try:
            catalogue = await client.get(
                f"{DATA_GOV_SG_API}/{spec.dataset_id}/poll-download"
            )
            catalogue.raise_for_status()
            body = catalogue.json()
            if body.get("code") != 0 or not body.get("data", {}).get("url"):
                raise RuntimeError(
                    f"data.gov.sg download lookup failed for {spec.dataset_id}: "
                    f"{body.get('errMsg') or body}"
                )
            download = await client.get(body["data"]["url"])
            download.raise_for_status()
            return download.content
        finally:
            if owned_client:
                await client.aclose()


class PublicGeoStore:
    """Raw official geometry kept beside the routeable POI catalogue.

    The existing hubs/outlets tables remain the optimiser's routeable place model.
    Lines and polygons do not fit that model, so they live here with bounding boxes
    for cheap map-window queries. This also lets us retain non-routeable datasets
    such as SportSG facilities whose public-access status is not published.
    """

    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS public_geo_features (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    name TEXT,
                    geometry_type TEXT NOT NULL,
                    geometry_json TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    min_lat REAL NOT NULL,
                    min_lon REAL NOT NULL,
                    max_lat REAL NOT NULL,
                    max_lon REAL NOT NULL,
                    last_verified_at TEXT,
                    routeable INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(source, source_id)
                );
                CREATE INDEX IF NOT EXISTS idx_public_geo_layer
                    ON public_geo_features(layer);
                CREATE INDEX IF NOT EXISTS idx_public_geo_bbox
                    ON public_geo_features(min_lat, max_lat, min_lon, max_lon);
                """
            )

    def replace_source(self, source: str, features: Iterable[dict[str, Any]]) -> int:
        records = list(features)
        with self._connect() as connection:
            connection.execute("DELETE FROM public_geo_features WHERE source=?", (source,))
            connection.executemany(
                """
                INSERT INTO public_geo_features(
                    source, source_id, dataset_id, layer, name, geometry_type,
                    geometry_json, properties_json, min_lat, min_lon, max_lat,
                    max_lon, last_verified_at, routeable
                ) VALUES (
                    :source, :source_id, :dataset_id, :layer, :name, :geometry_type,
                    :geometry_json, :properties_json, :min_lat, :min_lon, :max_lat,
                    :max_lon, :last_verified_at, :routeable
                )
                """,
                records,
            )
        return len(records)

    def counts_by_layer(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT layer, COUNT(*) AS count FROM public_geo_features "
                "GROUP BY layer ORDER BY layer"
            ).fetchall()
        return {str(row["layer"]): int(row["count"]) for row in rows}

    def feature_collection(
        self,
        layers: tuple[str, ...],
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        limit: int = 2000,
    ) -> dict[str, Any]:
        self.initialize()
        bounded_limit = max(1, min(int(limit), 5000))
        clauses = [
            "max_lat >= ?",
            "min_lat <= ?",
            "max_lon >= ?",
            "min_lon <= ?",
        ]
        params: list[Any] = [min_lat, max_lat, min_lon, max_lon]
        if layers:
            placeholders = ",".join("?" for _ in layers)
            clauses.append(f"layer IN ({placeholders})")
            params.extend(layers)
        params.append(bounded_limit + 1)
        query = (
            "SELECT source, source_id, dataset_id, layer, name, geometry_json, "
            "properties_json, last_verified_at, routeable "
            "FROM public_geo_features WHERE "
            + " AND ".join(clauses)
            + " ORDER BY layer, id LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        truncated = len(rows) > bounded_limit
        rows = rows[:bounded_limit]
        features = []
        for row in rows:
            properties = json.loads(row["properties_json"])
            properties.update(
                {
                    "_along_layer": row["layer"],
                    "_along_source": row["source"],
                    "_along_dataset_id": row["dataset_id"],
                    "_along_source_id": row["source_id"],
                    "_along_routeable": bool(row["routeable"]),
                    "_along_last_verified_at": row["last_verified_at"],
                }
            )
            if row["name"] and "name" not in {str(key).casefold() for key in properties}:
                properties["name"] = row["name"]
            features.append(
                {
                    "type": "Feature",
                    "geometry": json.loads(row["geometry_json"]),
                    "properties": properties,
                }
            )
        return {
            "type": "FeatureCollection",
            "features": features,
            "truncated": truncated,
            "limit": bounded_limit,
            "attribution": "Official Singapore datasets from data.gov.sg",
            "licence_url": OPEN_DATA_LICENCE_URL,
        }


class _TransitIndex:
    def __init__(self, rows: Iterable[tuple[str, str, float, float]]):
        self._items = list(rows)
        self._cell_size = 0.01
        self._buckets: dict[tuple[int, int], list[tuple[str, str, float, float]]] = {}
        for item in self._items:
            key = self._key(item[2], item[3])
            self._buckets.setdefault(key, []).append(item)

    def _key(self, latitude: float, longitude: float) -> tuple[int, int]:
        return (
            math.floor(latitude / self._cell_size),
            math.floor(longitude / self._cell_size),
        )

    def nearest(self, latitude: float, longitude: float) -> tuple[str, str, float] | None:
        if not self._items:
            return None
        cell = self._key(latitude, longitude)
        # Never stop at the first occupied cell: a point can sit on a grid
        # boundary while a much closer station is in the adjacent cell.
        # A 5x5 neighbourhood spans well beyond the optimiser's 1.2 km
        # transit-proximity threshold in Singapore; expand only when it is empty.
        candidates = [
            item
            for dx in range(-2, 3)
            for dy in range(-2, 3)
            for item in self._buckets.get((cell[0] + dx, cell[1] + dy), ())
        ]
        if not candidates:
            for radius in range(3, 8):
                candidates = [
                    item
                    for dx in range(-radius, radius + 1)
                    for dy in range(-radius, radius + 1)
                    for item in self._buckets.get((cell[0] + dx, cell[1] + dy), ())
                ]
                if candidates:
                    break
        if not candidates:
            candidates = self._items
        best = min(
            candidates,
            key=lambda item: _approx_distance_m(
                latitude, longitude, item[2], item[3]
            ),
        )
        return (
            best[0],
            best[1],
            _approx_distance_m(latitude, longitude, best[2], best[3]),
        )


def _approx_distance_m(
    latitude: float,
    longitude: float,
    other_latitude: float,
    other_longitude: float,
) -> float:
    latitude_scale = 110_570.0
    longitude_scale = 111_320.0 * math.cos(
        math.radians((latitude + other_latitude) / 2)
    )
    return math.hypot(
        (latitude - other_latitude) * latitude_scale,
        (longitude - other_longitude) * longitude_scale,
    )


def _load_transit_index(database_path: Path) -> _TransitIndex:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT id, name, latitude, longitude FROM transport_nodes"
        ).fetchall()
    return _TransitIndex(
        (str(row[0]), str(row[1]), float(row[2]), float(row[3])) for row in rows
    )


def _source_id(properties: dict[str, Any], index: int) -> str:
    for key in ("UNIQUEID", "OBJECTID", "OBJECTID_1", "INC_CRC"):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return f"feature-{index}"


def _verified_at(properties: dict[str, Any]) -> str | None:
    raw = properties.get("FMEL_UPD_D")
    if raw in (None, ""):
        return None
    digits = "".join(character for character in str(raw) if character.isdigit())
    if len(digits) < 8:
        return None
    try:
        if len(digits) >= 14:
            parsed = datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        else:
            parsed = datetime.strptime(digits[:8], "%Y%m%d")
        return parsed.replace(tzinfo=SINGAPORE_TZ).isoformat()
    except ValueError:
        return None


def _coordinate_bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[1]), float(value[0])))
            return
        if isinstance(value, list):
            for child in value:
                visit(child)

    visit(geometry.get("coordinates"))
    if not points:
        raise ValueError("Feature geometry has no coordinates")
    latitudes = [point[0] for point in points]
    longitudes = [point[1] for point in points]
    return min(latitudes), min(longitudes), max(latitudes), max(longitudes)


def _geo_record(
    spec: DatasetSpec,
    source_id: str,
    geometry: dict[str, Any],
    properties: dict[str, Any],
    *,
    name: str | None = None,
    layer: str | None = None,
    routeable: bool | None = None,
) -> dict[str, Any]:
    min_lat, min_lon, max_lat, max_lon = _coordinate_bounds(geometry)
    return {
        "source": spec.source,
        "source_id": source_id,
        "dataset_id": spec.dataset_id,
        "layer": layer or spec.layer,
        "name": name,
        "geometry_type": str(geometry.get("type") or "Unknown"),
        "geometry_json": json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
        "properties_json": json.dumps(
            properties, ensure_ascii=False, separators=(",", ":"), default=str
        ),
        "min_lat": min_lat,
        "min_lon": min_lon,
        "max_lat": max_lat,
        "max_lon": max_lon,
        "last_verified_at": _verified_at(properties),
        "routeable": 1 if (spec.routeable if routeable is None else routeable) else 0,
    }


def _internal_hub_name(spec: DatasetSpec, display_name: str, source_id: str) -> str:
    return f"{display_name} · data.gov.sg/{spec.dataset_id}:{source_id}"


def _hub(
    spec: DatasetSpec,
    source_id: str,
    name: str,
    latitude: float,
    longitude: float,
    *,
    address: str | None = None,
    opening_hours: str | None = None,
    closure_status: str = "unknown",
    last_verified_at: str | None = None,
) -> dict[str, Any]:
    return {
        "name": _internal_hub_name(spec, name, source_id),
        "latitude": latitude,
        "longitude": longitude,
        "semantic_type": "standalone",
        "transport_area_id": None,
        "consolidation_group_id": f"{spec.source}:{source_id}",
        "source": spec.source,
        "source_id": source_id,
        "last_verified_at": last_verified_at,
        "opening_hours": opening_hours,
        "closure_status": closure_status,
        "transport_node_distance_m": None,
        "address": address,
    }


def _outlet(
    spec: DatasetSpec,
    source_id: str,
    hub_source_id: str,
    name: str,
    categories: tuple[str, ...],
    *,
    closure_status: str = "unknown",
    last_verified_at: str | None = None,
    search_metadata: str | None = None,
) -> dict[str, Any]:
    return {
        "hub_source_id": hub_source_id,
        "name": name,
        "brand_slug": None,
        "categories": categories,
        "source": spec.source,
        "source_id": source_id,
        "last_verified_at": last_verified_at,
        "opening_hours": None,
        "closure_status": closure_status,
        "original_name": name,
        "alt_names": None,
        "cuisine": None,
        "shop": None,
        "amenity": None,
        "search_metadata": search_metadata,
        "brand_wikidata": None,
    }


def _point(feature: dict[str, Any]) -> tuple[float, float] | None:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    if (
        geometry.get("type") != "Point"
        or not isinstance(coordinates, list)
        or len(coordinates) < 2
    ):
        return None
    try:
        return float(coordinates[1]), float(coordinates[0])
    except (TypeError, ValueError):
        return None


def _geojson_features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("Expected a GeoJSON FeatureCollection")
    return [feature for feature in features if isinstance(feature, dict)]


def parse_mrt_exits(spec: DatasetSpec, payload: dict[str, Any]) -> ParsedDataset:
    nodes: list[dict[str, Any]] = []
    geo_features: list[dict[str, Any]] = []
    skipped = 0
    features = _geojson_features(payload)
    for index, feature in enumerate(features):
        coordinate = _point(feature)
        properties = feature.get("properties") or {}
        if coordinate is None:
            skipped += 1
            continue
        source_id = _source_id(properties, index)
        station = str(properties.get("STATION_NA") or "MRT station").strip()
        exit_code = str(properties.get("EXIT_CODE") or "Exit").strip()
        station_name = station.title().replace(" Mrt ", " MRT ").replace(" Lrt ", " LRT ")
        display_name = f"{station_name} {exit_code}"
        nodes.append(
            {
                "id": f"dgov:mrt-exit:{source_id}",
                "name": display_name,
                "latitude": coordinate[0],
                "longitude": coordinate[1],
                "node_type": "mrt_exit",
                "source": spec.source,
                "source_id": source_id,
                "last_verified_at": _verified_at(properties),
            }
        )
        geo_features.append(
            _geo_record(
                spec,
                source_id,
                feature["geometry"],
                properties,
                name=display_name,
                routeable=False,
            )
        )
    return ParsedDataset(spec, nodes, [], [], geo_features, len(features), skipped)


def parse_hawker_centres(spec: DatasetSpec, payload: dict[str, Any]) -> ParsedDataset:
    hubs: list[dict[str, Any]] = []
    outlets: list[dict[str, Any]] = []
    geo_features: list[dict[str, Any]] = []
    skipped = 0
    features = _geojson_features(payload)
    for index, feature in enumerate(features):
        coordinate = _point(feature)
        properties = feature.get("properties") or {}
        if coordinate is None:
            skipped += 1
            continue
        source_id = _source_id(properties, index)
        name = str(
            properties.get("NAME")
            or properties.get("ADDRESSBUILDINGNAME")
            or "Hawker centre"
        ).strip()
        status = str(properties.get("STATUS") or "").casefold()
        closure_status = (
            "open" if status == "existing" else "closed" if "closed" in status else "unknown"
        )
        address = properties.get("ADDRESS_MYENV")
        if not address:
            parts = [
                properties.get("ADDRESSBLOCKHOUSENUMBER"),
                properties.get("ADDRESSSTREETNAME"),
                properties.get("ADDRESSPOSTALCODE"),
            ]
            address = " ".join(str(item).strip() for item in parts if item not in (None, ""))
        verified = _verified_at(properties)
        stalls = properties.get("NUMBER_OF_COOKED_FOOD_STALLS")
        metadata = f"{stalls} cooked-food stalls" if stalls not in (None, "") else None
        hubs.append(
            _hub(
                spec,
                source_id,
                name,
                coordinate[0],
                coordinate[1],
                address=str(address).strip() if address else None,
                closure_status=closure_status,
                last_verified_at=verified,
            )
        )
        outlets.append(
            _outlet(
                spec,
                source_id,
                source_id,
                name,
                ("hawker_centres",),
                closure_status=closure_status,
                last_verified_at=verified,
                search_metadata=metadata,
            )
        )
        geo_features.append(
            _geo_record(
                spec,
                source_id,
                feature["geometry"],
                properties,
                name=name,
                routeable=True,
            )
        )
    return ParsedDataset(spec, [], hubs, outlets, geo_features, len(features), skipped)


def _park_facility_categories(class_name: str) -> tuple[str, ...]:
    normalized = normalize_text(class_name)
    if "fitness" in normalized or "exercise" in normalized:
        return ("fitness", "park_facilities")
    if "toilet" in normalized or "washroom" in normalized:
        return ("public_toilets", "park_facilities")
    if "playground" in normalized:
        return ("playgrounds", "park_facilities")
    if "carpark" in normalized or "car park" in normalized or "parking" in normalized:
        return ("parking", "park_facilities")
    if "dog run" in normalized:
        return ("dog_runs", "park_facilities")
    return ("park_facilities",)


def parse_park_facilities(spec: DatasetSpec, payload: dict[str, Any]) -> ParsedDataset:
    hubs: list[dict[str, Any]] = []
    outlets: list[dict[str, Any]] = []
    geo_features: list[dict[str, Any]] = []
    skipped = 0
    features = _geojson_features(payload)
    for index, feature in enumerate(features):
        coordinate = _point(feature)
        properties = feature.get("properties") or {}
        if coordinate is None:
            skipped += 1
            continue
        source_id = _source_id(properties, index)
        class_name = str(properties.get("CLASS") or "Park facility").strip()
        raw_name = str(properties.get("NAME") or "").strip()
        display_name = raw_name or class_name.title()
        verified = _verified_at(properties)
        categories = _park_facility_categories(class_name)
        hubs.append(
            _hub(
                spec,
                source_id,
                display_name,
                coordinate[0],
                coordinate[1],
                last_verified_at=verified,
            )
        )
        outlets.append(
            _outlet(
                spec,
                source_id,
                source_id,
                display_name,
                categories,
                last_verified_at=verified,
                search_metadata=class_name,
            )
        )
        geo_features.append(
            _geo_record(
                spec,
                source_id,
                feature["geometry"],
                properties,
                name=display_name,
                routeable=True,
            )
        )
    return ParsedDataset(spec, [], hubs, outlets, geo_features, len(features), skipped)


def parse_generic_geojson(spec: DatasetSpec, payload: dict[str, Any]) -> ParsedDataset:
    geo_features: list[dict[str, Any]] = []
    skipped = 0
    features = _geojson_features(payload)
    for index, feature in enumerate(features):
        geometry = feature.get("geometry")
        properties = feature.get("properties") or {}
        if not isinstance(geometry, dict) or not geometry.get("coordinates"):
            skipped += 1
            continue
        source_id = _source_id(properties, index)
        name_value = properties.get("NAME") or properties.get("PARK")
        name = str(name_value).strip() if name_value not in (None, "") else None
        layer = spec.layer
        if spec.key == "nparks_tracks":
            track_type = normalize_text(str(properties.get("TYPE") or ""))
            park_type = normalize_text(str(properties.get("PARK_TYPE") or ""))
            if (\n                "park connector" in track_type\n                or "park connector" in park_type\n                or "pcn" in track_type\n                or "pcn" in park_type\n            ):\n                layer = "park_connectors"
            else:
                layer = "park_tracks"
        try:
            geo_features.append(
                _geo_record(
                    spec,
                    source_id,
                    geometry,
                    properties,
                    name=name,
                    layer=layer,
                    routeable=False,
                )
            )
        except ValueError:
            skipped += 1
    return ParsedDataset(spec, [], [], [], geo_features, len(features), skipped)


def parse_sport_facilities(spec: DatasetSpec, raw: bytes) -> ParsedDataset:
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    geo_features: list[dict[str, Any]] = []
    skipped = 0
    seen: set[str] = set()
    for row in rows:
        try:
            latitude = float(row.get("Latitude") or "")
            longitude = float(row.get("Longitude") or "")
        except ValueError:
            skipped += 1
            continue
        venue = (row.get("VenueName") or "Sports facility").strip()
        facility = (row.get("SportsFacility") or "Sports facility").strip()
        postal_code = (row.get("PostalCode") or "").strip()
        identity = "|".join(
            (normalize_text(venue), postal_code, f"{latitude:.6f}", f"{longitude:.6f}", normalize_text(facility))
        )
        source_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]
        if source_id in seen:
            continue
        seen.add(source_id)
        properties = {
            "VenueName": venue,
            "PostalCode": postal_code or None,
            "SportsFacility": facility,
            "_along_access": "unknown",
        }
        geometry = {"type": "Point", "coordinates": [longitude, latitude]}
        geo_features.append(
            _geo_record(
                spec,
                source_id,
                geometry,
                properties,
                name=f"{venue} — {facility}",
                routeable=False,
            )
        )
    return ParsedDataset(spec, [], [], [], geo_features, len(rows), skipped)


def parse_dataset(spec: DatasetSpec, raw: bytes) -> ParsedDataset:
    if spec.file_format == "csv":
        if spec.key != "sport_facilities":
            raise ValueError(f"No CSV parser configured for {spec.key}")
        return parse_sport_facilities(spec, raw)
    payload = json.loads(raw.decode("utf-8-sig"))
    if spec.key == "mrt_exits":
        return parse_mrt_exits(spec, payload)
    if spec.key == "hawker_centres":
        return parse_hawker_centres(spec, payload)
    if spec.key == "park_facilities":
        return parse_park_facilities(spec, payload)
    return parse_generic_geojson(spec, payload)


def _attach_transit_context(parsed: ParsedDataset, index: _TransitIndex) -> None:
    for hub in parsed.hubs:
        nearest = index.nearest(float(hub["latitude"]), float(hub["longitude"]))
        if nearest is None:
            continue
        hub["transport_area_id"] = nearest[0]
        hub["transport_node_distance_m"] = round(nearest[2], 1)


def ingest_parsed_dataset(
    repository: HubRepository,
    geo_store: PublicGeoStore,
    parsed: ParsedDataset,
) -> PublicDataIngestionReport:
    if parsed.transport_nodes:
        repository.replace_source_data(
            parsed.spec.source,
            parsed.transport_nodes,
            parsed.hubs,
            parsed.outlets,
        )
    else:
        transit_index = _load_transit_index(repository.path)
        _attach_transit_context(parsed, transit_index)
        repository.replace_source_data(
            parsed.spec.source,
            [],
            parsed.hubs,
            parsed.outlets,
        )
    geo_store.replace_source(parsed.spec.source, parsed.geo_features)
    return PublicDataIngestionReport(
        key=parsed.spec.key,
        dataset_id=parsed.spec.dataset_id,
        rows_seen=parsed.rows_seen,
        transport_nodes=len(parsed.transport_nodes),
        hubs=len(parsed.hubs),
        outlets=len(parsed.outlets),
        geo_features=len(parsed.geo_features),
        skipped=parsed.skipped,
    )
