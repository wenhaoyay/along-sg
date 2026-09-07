from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.db import HUB_SEED, HubRepository
from app.domain import Coordinate
from app.poi_taxonomy import canonical_brand, infer_categories, normalize_text
from app.providers.mock import haversine_km


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_FALLBACK_URLS = (
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
)
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OSM_LICENSE_URL = "https://www.openstreetmap.org/copyright"

SINGAPORE_POI_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="SG"][admin_level=2]->.sg;
(
  nwr(area.sg)[amenity~"^(fast_food|cafe|restaurant|food_court|pharmacy|atm|bank|parcel_locker|parcel_pickup|printer)$"];
  nwr(area.sg)[shop~"^(supermarket|chemist|pharmacy|convenience|electronics|computer|mobile_phone|appliance|coffee|tea|bakery|pastry|confectionery|stationery|copyshop|printing|hardware|doityourself|florist|garden_centre|pet|pet_grooming|clothes|shoes|fashion|department_store|houseware|furniture|interior_decoration|variety_store|hairdresser|barber|optician|medical_supply|repair|car_repair|bicycle_repair|mobile_phone_repair|mall)$"];
  nwr(area.sg)[parcel_pickup="yes"];
  nwr(area.sg)[public_transport="station"];
  nwr(area.sg)[railway="station"];
);
out center tags bb;
""".strip()


@dataclass(frozen=True)
class IngestionReport:
    raw_elements: int
    raw_pois: int
    imported_pois: int
    imported_hubs: int
    imported_malls: int
    imported_transport_nodes: int
    deduplicated_pois: int
    closed_pois: int
    known_opening_hours: int
    canonical_brand_pois: int
    captured_at: str


def _coordinate(element: dict[str, Any]) -> Coordinate | None:
    if "lat" in element and "lon" in element:
        return Coordinate(float(element["lat"]), float(element["lon"]))
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return Coordinate(float(center["lat"]), float(center["lon"]))
    return None


def _source_id(element: dict[str, Any]) -> str:
    return f"{element.get('type', 'unknown')}/{element['id']}"


def _is_closed(tags: dict[str, str]) -> bool:
    if any(key.startswith(("disused:", "abandoned:")) for key in tags):
        return True
    status = " ".join(
        str(tags.get(key, "")).casefold()
        for key in ("opening_hours", "operational_status", "status")
    )
    return status.strip() in {"closed", "off", "permanently closed"} or bool(tags.get("end_date"))


def _address(tags: dict[str, str]) -> str | None:
    street = tags.get("addr:street") or tags.get("addr:place")
    number = tags.get("addr:housenumber")
    postcode = tags.get("addr:postcode")
    parts = [" ".join(item for item in (number, street) if item), postcode]
    value = ", Singapore ".join(item for item in parts if item)
    return value or tags.get("contact:address") or tags.get("address")


def _inside_bounds(coordinate: Coordinate, element: dict[str, Any], margin: float = 0.00015) -> bool:
    bounds = element.get("bounds")
    if not isinstance(bounds, dict):
        return False
    return (
        float(bounds["minlat"]) - margin <= coordinate.latitude <= float(bounds["maxlat"]) + margin
        and float(bounds["minlon"]) - margin <= coordinate.longitude <= float(bounds["maxlon"]) + margin
    )


def _unique_name(name: str, source_id: str, used: set[str]) -> str:
    candidate = name.strip() or f"Unnamed place {source_id}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    candidate = f"{candidate} · {source_id}"
    used.add(candidate)
    return candidate


def transform_osm_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], IngestionReport]:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("OSM payload must contain an elements list")
    captured_at = str(
        payload.get("capture_metadata", {}).get("captured_at")
        or datetime.now(timezone.utc).isoformat()
    )
    source = "openstreetmap"
    malls: list[tuple[dict[str, Any], Coordinate]] = []
    stations: list[tuple[dict[str, Any], Coordinate]] = []
    pois: list[tuple[dict[str, Any], Coordinate, tuple[str, ...]]] = []
    raw_pois = 0
    for element in elements:
        tags = element.get("tags") or {}
        coordinate = _coordinate(element)
        if coordinate is None or not (1.13 <= coordinate.latitude <= 1.48 and 103.58 <= coordinate.longitude <= 104.10):
            continue
        if tags.get("shop") == "mall":
            malls.append((element, coordinate))
        if tags.get("public_transport") == "station" or tags.get("railway") == "station":
            stations.append((element, coordinate))
        categories = infer_categories(tags)
        if categories:
            raw_pois += 1
            pois.append((element, coordinate, categories))

    nodes: list[dict[str, Any]] = []
    station_lookup: list[tuple[str, Coordinate]] = []
    seen_station_ids: set[str] = set()
    for element, coordinate in stations:
        source_id = _source_id(element)
        if source_id in seen_station_ids:
            continue
        seen_station_ids.add(source_id)
        node_id = f"osm:{source_id}"
        tags = element.get("tags") or {}
        nodes.append({
            "id": node_id,
            "name": tags.get("name") or f"Transport node {source_id}",
            "latitude": coordinate.latitude,
            "longitude": coordinate.longitude,
            "node_type": tags.get("railway") or tags.get("public_transport") or "station",
            "source": source,
            "source_id": source_id,
            "last_verified_at": captured_at,
        })
        station_lookup.append((node_id, coordinate))

    def nearest_station(coordinate: Coordinate) -> tuple[str | None, float | None]:
        if not station_lookup:
            return None, None
        node_id, node_coordinate = min(
            station_lookup,
            key=lambda item: haversine_km(coordinate, item[1]),
        )
        distance_m = haversine_km(coordinate, node_coordinate) * 1000
        return (node_id, round(distance_m, 1)) if distance_m <= 1200 else (None, round(distance_m, 1))

    used_names = {row[1] for row in HUB_SEED}
    hubs: list[dict[str, Any]] = []
    mall_lookup: list[tuple[str, dict[str, Any], Coordinate]] = []
    for element, coordinate in malls:
        source_id = f"mall:{_source_id(element)}"
        tags = element.get("tags") or {}
        transport_id, transport_distance = nearest_station(coordinate)
        hubs.append({
            "name": _unique_name(tags.get("name") or "Shopping mall", source_id, used_names),
            "latitude": coordinate.latitude,
            "longitude": coordinate.longitude,
            "semantic_type": "mall",
            "transport_area_id": transport_id,
            "consolidation_group_id": source_id,
            "source": source,
            "source_id": source_id,
            "last_verified_at": captured_at,
            "opening_hours": tags.get("opening_hours"),
            "closure_status": "closed" if _is_closed(tags) else "unknown",
            "transport_node_distance_m": transport_distance,
            "address": _address(tags),
        })
        mall_lookup.append((source_id, element, coordinate))

    dedupe_seen: list[tuple[str, Coordinate]] = []
    outlets: list[dict[str, Any]] = []
    deduplicated = 0
    closed_count = 0
    known_hours = 0
    branded = 0
    outlet_hub_seen: set[tuple[str, str, str]] = set()
    for element, coordinate, categories in sorted(pois, key=lambda item: _source_id(item[0])):
        tags = element.get("tags") or {}
        source_id = _source_id(element)
        brand_slug, canonical_name = canonical_brand(tags.get("brand"), tags.get("operator"), tags.get("name"))
        display_name = canonical_name or tags.get("name") or f"{categories[0].replace('_', ' ').title()} {source_id}"
        dedupe_key = f"{brand_slug or normalize_text(display_name)}|{','.join(categories)}"
        if any(key == dedupe_key and haversine_km(coordinate, previous) <= 0.025 for key, previous in dedupe_seen):
            deduplicated += 1
            continue
        dedupe_seen.append((dedupe_key, coordinate))

        containing_malls = [
            item for item in mall_lookup if _inside_bounds(coordinate, item[1])
        ]
        if containing_malls:
            hub_source_id, _mall_element, _mall_coordinate = min(
                containing_malls, key=lambda item: haversine_km(coordinate, item[2])
            )
        else:
            nearby_malls = [
                item for item in mall_lookup
                if haversine_km(coordinate, item[2]) <= 0.075
            ]
            if nearby_malls:
                hub_source_id, _mall_element, _mall_coordinate = min(
                    nearby_malls, key=lambda item: haversine_km(coordinate, item[2])
                )
            else:
                hub_source_id = f"poi:{source_id}"
                transport_id, transport_distance = nearest_station(coordinate)
                hubs.append({
                    "name": _unique_name(display_name, source_id, used_names),
                    "latitude": coordinate.latitude,
                    "longitude": coordinate.longitude,
                    "semantic_type": "station_area" if transport_distance is not None and transport_distance <= 150 else "standalone",
                    "transport_area_id": transport_id,
                    "consolidation_group_id": hub_source_id,
                    "source": source,
                    "source_id": hub_source_id,
                    "last_verified_at": captured_at,
                    "opening_hours": tags.get("opening_hours"),
                    "closure_status": "closed" if _is_closed(tags) else "unknown",
                    "transport_node_distance_m": transport_distance,
                    "address": _address(tags),
                })
        hub_dedupe_key = (hub_source_id, normalize_text(display_name), categories[0])
        if hub_dedupe_key in outlet_hub_seen:
            deduplicated += 1
            continue
        outlet_hub_seen.add(hub_dedupe_key)
        is_closed = _is_closed(tags)
        closed_count += int(is_closed)
        known_hours += int(bool(tags.get("opening_hours")))
        branded += int(bool(brand_slug))
        outlets.append({
            "hub_source_id": hub_source_id,
            "name": display_name,
            "original_name": tags.get("name"),
            "alt_names": " | ".join(filter(None, (
                tags.get("alt_name"), tags.get("short_name"), tags.get("loc_name"),
                tags.get("official_name"), tags.get("name:en"),
            ))) or None,
            "cuisine": tags.get("cuisine"),
            "shop": tags.get("shop"),
            "amenity": tags.get("amenity"),
            "search_metadata": " | ".join(filter(None, (
                tags.get("description"), tags.get("operator"), tags.get("branch"),
                tags.get("addr:street"), tags.get("addr:place"), tags.get("addr:postcode"),
            ))) or None,
            "brand_slug": brand_slug,
            "categories": categories,
            "source": source,
            "source_id": source_id,
            "last_verified_at": captured_at,
            "opening_hours": tags.get("opening_hours"),
            "closure_status": "closed" if is_closed else "unknown",
        })

    report = IngestionReport(
        raw_elements=len(elements), raw_pois=raw_pois, imported_pois=len(outlets),
        imported_hubs=len(hubs), imported_malls=len(malls),
        imported_transport_nodes=len(nodes), deduplicated_pois=deduplicated,
        closed_pois=closed_count, known_opening_hours=known_hours,
        canonical_brand_pois=branded, captured_at=captured_at,
    )
    return nodes, hubs, outlets, report


async def download_osm_payload(url: str | None = None) -> dict[str, Any]:
    urls = (url,) if url else OVERPASS_FALLBACK_URLS
    last_error: Exception | None = None
    payload: dict[str, Any] | None = None
    used_url: str | None = None
    headers = {"User-Agent": "AlongTheWay-V0.5/0.5 (Singapore POI ingestion)"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(210.0), headers=headers) as client:
        for candidate_url in urls:
            try:
                response = await client.post(
                    candidate_url,
                    content=SINGAPORE_POI_QUERY.encode("utf-8"),
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                response.raise_for_status()
                payload = response.json()
                used_url = candidate_url
                break
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
    if payload is None:
        raise RuntimeError("All bounded public Overpass download attempts failed") from last_error
    payload["capture_metadata"] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap via Overpass API",
        "scope": "Singapore only",
        "attribution": OSM_ATTRIBUTION,
        "license": "ODbL 1.0",
        "license_url": OSM_LICENSE_URL,
        "query": SINGAPORE_POI_QUERY,
        "endpoint": used_url,
    }
    return payload


def ingest_payload(repository: HubRepository, payload: dict[str, Any]) -> IngestionReport:
    nodes, hubs, outlets, report = transform_osm_payload(payload)
    repository.replace_source_data("openstreetmap", nodes, hubs, outlets)
    return report


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
