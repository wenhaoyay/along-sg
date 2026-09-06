from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.domain import Hub, Store
from app.poi_taxonomy import CATEGORIES


logger = logging.getLogger("presentation")
_RAW_ID = re.compile(r"(?:\s*[·-]\s*)?(?:node|way|relation)/\d+", re.IGNORECASE)
_CATEGORY_LABELS = {item.slug: item.name for item in CATEGORIES}


def safe_label(value: str | None, fallback: str = "Location details unavailable") -> str:
    cleaned = _RAW_ID.sub("", (value or "")).strip(" ·-—")
    if not cleaned:
        logger.warning("Missing consumer-facing label; using safe fallback")
        return fallback
    return cleaned


def hub_display_name(hub: Hub) -> str:
    label = safe_label(hub.name)
    store_labels = sorted({store_display_name(store) for store in hub.stores})
    store_names = {item.casefold() for item in store_labels}
    if hub.semantic_type == "standalone" and (
        hub.source == "openstreetmap" or label.casefold() in store_names
    ):
        business = store_labels[0] if store_labels else label
        return business
    return label


@dataclass(frozen=True)
class DisplayLocation:
    context: str
    kind: str
    quality: float
    navigation_ready: bool


_AREA_CENTRES = (
    ("Woodlands", 1.4360, 103.7865), ("Yishun", 1.4295, 103.8353),
    ("Sengkang", 1.3917, 103.8950), ("Punggol", 1.4043, 103.9020),
    ("Pasir Ris", 1.3730, 103.9493), ("Tampines", 1.3521, 103.9449),
    ("Bedok", 1.3240, 103.9300), ("Paya Lebar", 1.3175, 103.8920),
    ("Serangoon", 1.3509, 103.8485), ("Bishan", 1.3508, 103.8485),
    ("Toa Payoh", 1.3343, 103.8563), ("Orchard", 1.3048, 103.8318),
    ("City Hall", 1.2932, 103.8520), ("HarbourFront", 1.2653, 103.8223),
    ("Queenstown", 1.2942, 103.7861), ("Clementi", 1.3151, 103.7650),
    ("Jurong East", 1.3331, 103.7422), ("Boon Lay", 1.3386, 103.7061),
    ("Choa Chu Kang", 1.3854, 103.7443), ("Bukit Panjang", 1.3774, 103.7630),
)


def hub_location_context(hub: Hub) -> DisplayLocation:
    if hub.address:
        context = safe_label(hub.address, "Singapore")
        return DisplayLocation(context, "address", 1.0, True)
    label = safe_label(hub.name, "Singapore")
    if hub.semantic_type == "mall":
        return DisplayLocation(label, "mall", 0.95, True)
    if hub.semantic_type == "station_area" and hub.transport_node_name:
        return DisplayLocation(f"Near {safe_label(hub.transport_node_name)}", "station_area", 0.88, True)
    if hub.nearby_context_name:
        distance = f" · {round(hub.nearby_context_distance_m or 0):.0f} m away" if hub.nearby_context_distance_m else ""
        return DisplayLocation(f"Near {safe_label(hub.nearby_context_name)}{distance}", "nearby_mall", 0.82, True)
    if hub.transport_node_name:
        distance = f" · {round(hub.transport_node_distance_m or 0):.0f} m" if hub.transport_node_distance_m else ""
        return DisplayLocation(f"Near {safe_label(hub.transport_node_name)}{distance}", "station", 0.72, True)
    area = min(
        _AREA_CENTRES,
        key=lambda item: (hub.coordinate.latitude - item[1]) ** 2 + (hub.coordinate.longitude - item[2]) ** 2,
    )[0]
    return DisplayLocation(f"{area} area", "area", 0.5, True)


def hub_data_quality(hub: Hub) -> float:
    location = hub_location_context(hub)
    hours_bonus = 0.05 if hub.opening_hours or any(store.opening_hours for store in hub.stores) else 0.0
    return min(1.0, location.quality + hours_bonus)


def store_display_name(store: Store) -> str:
    return safe_label(store.canonical_brand or store.name, "Business details unavailable")


def category_label(slug: str) -> str:
    return _CATEGORY_LABELS.get(slug, slug.replace("_", " ").title())


def contains_raw_identifier(value: str) -> bool:
    return _RAW_ID.search(value) is not None
