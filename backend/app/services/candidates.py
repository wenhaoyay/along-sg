from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from itertools import product, permutations

from app.db import HubRepository
from app.domain import CandidateOption, Coordinate, Hub, NearMissCandidate, RouteResult
from app.poi_taxonomy import CATEGORY_ALIASES, NEAR_MISS_SUBSTITUTES, normalize_text
from app.providers.mock import haversine_km


@dataclass(frozen=True)
class CandidatePipelineResult:
    candidates: tuple[CandidateOption, ...]
    near_misses: tuple[NearMissCandidate, ...]
    raw_poi_count: int
    category_match_hub_count: int
    corridor_hub_count: int
    transit_proximity_hub_count: int
    hub_coverage_candidate_count: int
    approximate_detour_candidate_count: int
    baseline_geometry_point_count: int


def normalize_categories(errands: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for errand in errands:
        key = errand.strip().casefold()
        category = CATEGORY_ALIASES.get(key, key)
        if category and category not in normalized:
            normalized.append(category)
    return tuple(normalized)


def generate_candidates(repository: HubRepository, categories: tuple[str, ...]) -> list[CandidateOption]:
    if not 1 <= len(categories) <= 2:
        raise ValueError("V0 supports one or two distinct errand categories")
    hubs = repository.find_for_categories(categories)
    return generate_candidates_from_hubs(hubs, categories)


def generate_candidates_from_hubs(
    hubs: list[Hub],
    categories: tuple[str, ...],
) -> list[CandidateOption]:
    if len(categories) == 1:
        return [
            CandidateOption(
                (hub,),
                categories,
                consolidated=False,
                stop_category_assignments=((hub.id, categories),),
                stop_relationship="single_stop",
            )
            for hub in hubs
            if categories[0] in hub.categories
        ]

    first, second = categories
    consolidated = [
        CandidateOption(
            (hub,),
            categories,
            consolidated=True,
            stop_category_assignments=((hub.id, categories),),
            stop_relationship="same_mall" if hub.semantic_type == "mall" else "same_place",
        )
        for hub in hubs
        if {first, second}.issubset(hub.categories)
    ]
    first_hubs = [hub for hub in hubs if first in hub.categories]
    second_hubs = [hub for hub in hubs if second in hub.categories]
    separate: list[CandidateOption] = []
    seen: set[tuple[int, int]] = set()
    for first_hub, second_hub in product(first_hubs, second_hubs):
        if first_hub.id == second_hub.id:
            continue
        # A hub that has both errands is already an option on its own, and
        # adding a second building to it only adds a stop. Pairs like that
        # filled routing slots that a genuinely separate pair needed.
        if {first, second}.issubset(first_hub.categories) or {first, second}.issubset(second_hub.categories):
            continue
        ids = tuple(sorted((first_hub.id, second_hub.id)))
        if ids in seen:
            continue
        seen.add(ids)
        ordered = tuple(sorted((first_hub, second_hub), key=lambda hub: hub.id))
        assignments = tuple(
            (hub.id, (first,) if hub.id == first_hub.id else (second,))
            for hub in ordered
        )
        separate.append(
            CandidateOption(
                ordered,
                categories,
                consolidated=False,
                stop_category_assignments=assignments,
                stop_relationship=classify_stop_relationship(ordered),
            )
        )
    return consolidated + separate


def decode_polyline(points: str, precision: int = 5) -> tuple[Coordinate, ...]:
    coordinates: list[Coordinate] = []
    latitude = longitude = index = 0
    factor = 10**precision
    while index < len(points):
        values: list[int] = []
        for _ in range(2):
            result = shift = 0
            while True:
                if index >= len(points):
                    return tuple(coordinates)
                byte = ord(points[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            values.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += values[0]
        longitude += values[1]
        coordinates.append(Coordinate(latitude / factor, longitude / factor))
    return tuple(coordinates)


def baseline_geometry(
    route: RouteResult,
    origin: Coordinate,
    destination: Coordinate,
) -> tuple[Coordinate, ...]:
    points: list[Coordinate] = []
    for leg in route.legs:
        if not leg.geometry:
            continue
        if leg.geometry_format == "encoded_polyline" or leg.geometry_format is None:
            decoded = decode_polyline(leg.geometry)
            if decoded:
                points.extend(decoded if not points else decoded[1:])
    singapore_points = [
        point for point in points
        if 1.1 <= point.latitude <= 1.5 and 103.5 <= point.longitude <= 104.1
    ]
    return tuple(singapore_points) if len(singapore_points) >= 2 else (origin, destination)


def _point_segment_distance_km(point: Coordinate, start: Coordinate, end: Coordinate) -> float:
    reference_latitude = math.radians((start.latitude + end.latitude + point.latitude) / 3)
    scale_x = 111.32 * math.cos(reference_latitude)
    scale_y = 110.57
    px, py = point.longitude * scale_x, point.latitude * scale_y
    ax, ay = start.longitude * scale_x, start.latitude * scale_y
    bx, by = end.longitude * scale_x, end.latitude * scale_y
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + fraction * dx), py - (ay + fraction * dy))


# Segments per bounding box in the geometry index below.
_GEOMETRY_CHUNK = 8
_GEOMETRY_INDEX_MAX_ENTRIES = 32
_geometry_index_lock = threading.Lock()
# id(geometry) -> (geometry, chunk boxes, per-point memo). The entry holds the
# geometry itself, so its id cannot be reused by another object while cached.
_geometry_index: OrderedDict[
    int,
    tuple[
        tuple[Coordinate, ...],
        tuple[tuple[float, float, float, float, float, int, int], ...],
        dict[tuple[float, float], float],
    ],
] = OrderedDict()


def _indexed_geometry(
    geometry: tuple[Coordinate, ...],
) -> tuple[tuple[tuple[float, float, float, float, float, int, int], ...], dict[tuple[float, float], float]]:
    key = id(geometry)
    with _geometry_index_lock:
        entry = _geometry_index.get(key)
        if entry is not None and entry[0] is geometry:
            _geometry_index.move_to_end(key)
            return entry[1], entry[2]
    chunks = []
    for start in range(0, len(geometry) - 1, _GEOMETRY_CHUNK):
        end = min(start + _GEOMETRY_CHUNK, len(geometry) - 1)
        latitudes = [item.latitude for item in geometry[start:end + 1]]
        longitudes = [item.longitude for item in geometry[start:end + 1]]
        widest = max(abs(min(latitudes)), abs(max(latitudes)))
        chunks.append((
            min(latitudes), max(latitudes), min(longitudes), max(longitudes),
            math.cos(math.radians(widest)), start, end,
        ))
    built = (tuple(chunks), {})
    with _geometry_index_lock:
        _geometry_index[key] = (geometry, *built)
        while len(_geometry_index) > _GEOMETRY_INDEX_MAX_ENTRIES:
            _geometry_index.popitem(last=False)
    return built


def distance_to_geometry_km(point: Coordinate, geometry: tuple[Coordinate, ...]) -> float:
    """Exact minimum of `_point_segment_distance_km` over every segment.

    Exact, not approximate: a candidate's corridor test and its network rank
    both read this value, so a simplified polyline could move the answer.
    Speed comes from skipping segments that cannot be nearest. Segments are
    boxed in runs of eight; a box's distance, scaled with the smallest
    longitude factor any of its segments could use, is a lower bound on every
    segment inside it, so boxes are visited nearest first and the scan stops
    at the first box no closer than the best segment found. The result for a
    point is memoised per geometry, which ranking asks for repeatedly.
    """
    if len(geometry) < 2:
        return float("inf")
    if not isinstance(geometry, tuple):
        # Only an immutable geometry may be indexed by identity.
        return min(
            _point_segment_distance_km(point, geometry[index], geometry[index + 1])
            for index in range(len(geometry) - 1)
        )
    chunks, memo = _indexed_geometry(geometry)
    latitude, longitude = point.latitude, point.longitude
    memo_key = (latitude, longitude)
    known = memo.get(memo_key)
    if known is not None:
        return known
    point_cos = math.cos(math.radians(abs(latitude)))
    bounds = []
    for low_lat, high_lat, low_lon, high_lon, chunk_cos, start, end in chunks:
        delta_lat = low_lat - latitude if latitude < low_lat else (
            latitude - high_lat if latitude > high_lat else 0.0
        )
        delta_lon = low_lon - longitude if longitude < low_lon else (
            longitude - high_lon if longitude > high_lon else 0.0
        )
        scale_x = 111.32 * min(chunk_cos, point_cos)
        # Squared, and shaved by a part in a billion against rounding.
        bound = ((delta_lon * scale_x) ** 2 + (delta_lat * 110.57) ** 2) * (1 - 1e-9)
        bounds.append((bound, start, end))
    bounds.sort()
    best = float("inf")
    best_squared = float("inf")
    for bound, start, end in bounds:
        if bound >= best_squared:
            break
        for index in range(start, end):
            distance = _point_segment_distance_km(point, geometry[index], geometry[index + 1])
            if distance < best:
                best = distance
                best_squared = distance * distance
    memo[memo_key] = best
    return best


def _hub_access_km(hub: Hub, geometry: tuple[Coordinate, ...]) -> float:
    """One hub's share of `transit_access_rank_km`: leaving the route there and back, plus the walk to its station."""
    leave = 2 * distance_to_geometry_km(hub.coordinate, geometry) if geometry else 0.0
    walk = (hub.transport_node_distance_m / 1000) if hub.transport_node_distance_m is not None else 1.0
    return leave + walk


def _coverage_rank(
    hub: Hub,
    categories: tuple[str, ...],
    origin: Coordinate,
    destination: Coordinate,
) -> tuple[float, ...]:
    coverage = len(set(categories) & hub.categories)
    transit_distance = hub.transport_node_distance_m if hub.transport_node_distance_m is not None else 99999.0
    return (
        -coverage,
        0 if hub.semantic_type in {"mall", "station_area"} else 1,
        straight_line_detour_km(origin, destination, (hub,)),
        transit_distance,
        hub.id,
    )


def staged_candidate_pipeline(
    repository: HubRepository,
    categories: tuple[str, ...],
    origin: Coordinate,
    destination: Coordinate,
    baseline: RouteResult,
    max_candidates: int,
    max_detour_km: float,
    corridor_km: float = 2.5,
    endpoint_radius_km: float = 2.0,
    max_transit_node_distance_m: float = 1200.0,
    max_hubs_per_category: int = 8,
    exact_brands: tuple[tuple[str, str], ...] = (),
    exact_places: tuple[tuple[str, str], ...] = (),
    extra_hubs: tuple[Hub, ...] = (),
) -> CandidatePipelineResult:
    geometry = baseline_geometry(baseline, origin, destination)
    category_hubs = repository.find_for_categories(categories)
    known_ids = {hub.id for hub in category_hubs}
    category_hubs.extend(
        hub for hub in extra_hubs
        if hub.id not in known_ids and set(categories) & hub.categories
    )
    corridor_hubs = [
        hub for hub in category_hubs
        if distance_to_geometry_km(hub.coordinate, geometry) <= corridor_km
        or min(haversine_km(origin, hub.coordinate), haversine_km(destination, hub.coordinate)) <= endpoint_radius_km
    ]
    if not corridor_hubs:
        # A soft spatial corridor must not turn a catalog match into a dead end.
        corridor_hubs = sorted(
            category_hubs,
            key=lambda hub: _coverage_rank(hub, categories, origin, destination),
        )[:max(max_candidates * 3, max_hubs_per_category)]
    transit_hubs = [
        hub for hub in corridor_hubs
        if hub.semantic_type in {"mall", "station_area"}
        or (
            hub.transport_node_distance_m is not None
            and hub.transport_node_distance_m <= max_transit_node_distance_m
        )
        or min(haversine_km(origin, hub.coordinate), haversine_km(destination, hub.coordinate)) <= endpoint_radius_km
    ]
    if not transit_hubs:
        transit_hubs = corridor_hubs

    # Spatial filters are a shortlist heuristic. Preserve coverage of each
    # requested need when filtering would otherwise erase an entire errand.
    # Actual route time and the existing detour/request budgets remain decisive.
    for category in categories:
        if not any(category in hub.categories for hub in transit_hubs):
            alternatives = sorted(
                (hub for hub in category_hubs if category in hub.categories),
                key=lambda hub: _coverage_rank(hub, categories, origin, destination),
            )[:min(2, max_hubs_per_category)]
            transit_hubs.extend(hub for hub in alternatives if hub not in transit_hubs)

    ranked_hubs = sorted(
        transit_hubs,
        key=lambda hub: _coverage_rank(hub, categories, origin, destination),
    )
    if len(categories) == 1:
        selected_hubs = ranked_hubs[: max(max_candidates * 3, max_hubs_per_category)]
    else:
        selected_by_id: dict[int, Hub] = {
            hub.id: hub for hub in ranked_hubs
            if set(categories).issubset(hub.categories)
        }
        # Hubs that hold only one of the errands are chosen by how cheaply the
        # network reaches them, not by coverage: sorted coverage-first, malls
        # holding both filled every slot, and the single-errand shop beside the
        # origin that made the best two-stop plan was never considered.
        for category in categories:
            matches = sorted(
                (hub for hub in ranked_hubs if category in hub.categories and hub.id not in selected_by_id),
                key=lambda hub: (_hub_access_km(hub, geometry), hub.id),
            )
            selected_by_id.update({hub.id: hub for hub in matches[:max_hubs_per_category]})
        selected_hubs = list(selected_by_id.values())

    coverage_options = [
        option for option in generate_candidates_from_hubs(selected_hubs, categories)
        if option_satisfies_exact_brands(option, exact_brands)
        and option_satisfies_exact_places(option, exact_places)
    ]
    if not coverage_options and (exact_brands or exact_places):
        exact_by_category = dict(exact_brands)
        places_by_category = {category: normalize_text(place) for category, place in exact_places}
        exact_selected: dict[int, Hub] = {}
        for category in categories:
            matching = []
            for hub in category_hubs:
                if category not in hub.categories:
                    continue
                brand = exact_by_category.get(category)
                place = places_by_category.get(category)
                if brand and not any(store.canonical_brand == brand and category in store.all_categories for store in hub.stores):
                    continue
                if place and not any(normalize_text(store.name) == place and category in store.all_categories for store in hub.stores):
                    continue
                matching.append(hub)
            matching.sort(key=lambda hub: _coverage_rank(hub, categories, origin, destination))
            exact_selected.update({hub.id: hub for hub in matching[:max_hubs_per_category]})
        coverage_options = [
            option for option in generate_candidates_from_hubs(list(exact_selected.values()), categories)
            if option_satisfies_exact_brands(option, exact_brands)
            and option_satisfies_exact_places(option, exact_places)
        ]
    pruned = prune_candidates(
        coverage_options, origin, destination, max_candidates, max_detour_km,
        geometry=geometry,
    )
    near_misses = list(
        generate_near_misses(repository, categories, origin, destination)
    )

    return CandidatePipelineResult(
        candidates=tuple(pruned),
        near_misses=tuple(near_misses),
        raw_poi_count=repository.count_outlets(active_only=True),
        category_match_hub_count=len(category_hubs),
        corridor_hub_count=len(corridor_hubs),
        transit_proximity_hub_count=len(transit_hubs),
        hub_coverage_candidate_count=len(coverage_options),
        approximate_detour_candidate_count=len(pruned),
        baseline_geometry_point_count=len(geometry),
    )


def option_satisfies_exact_brands(
    option: CandidateOption,
    exact_brands: tuple[tuple[str, str], ...],
) -> bool:
    for category, brand in exact_brands:
        matching = False
        for stop in option.stops:
            if category not in option.categories_at(stop.id):
                continue
            if any(
                store.canonical_brand == brand and category in store.all_categories
                for store in stop.stores
            ):
                matching = True
                break
        if not matching:
            return False
    return True


def option_satisfies_exact_places(
    option: CandidateOption,
    exact_places: tuple[tuple[str, str], ...],
) -> bool:
    for category, place in exact_places:
        needle = normalize_text(place)
        if not any(
            category in option.categories_at(stop.id)
            and any(normalize_text(store.name) == needle and category in store.all_categories
                    for store in stop.stores)
            for stop in option.stops
        ):
            return False
    return True


def generate_near_misses(
    repository: HubRepository,
    categories: tuple[str, ...],
    origin: Coordinate,
    destination: Coordinate,
) -> tuple[NearMissCandidate, ...]:
    near_misses: list[NearMissCandidate] = []
    for requested in categories:
        for substitute in NEAR_MISS_SUBSTITUTES.get(requested, ()):
            substitute_hubs = repository.find_for_categories((substitute,))
            if not substitute_hubs:
                continue
            closest = min(
                substitute_hubs,
                key=lambda hub: straight_line_detour_km(
                    origin, destination, (hub,)
                ),
            )
            near_misses.append(
                NearMissCandidate(
                    requested,
                    substitute,
                    closest,
                    straight_line_detour_km(origin, destination, (closest,)),
                )
            )
    return tuple(near_misses)


def classify_stop_relationship(stops: tuple[Hub, ...]) -> str:
    if len(stops) <= 1:
        return "single_stop"
    consolidation_groups = {stop.consolidation_group_id for stop in stops}
    if None not in consolidation_groups and len(consolidation_groups) == 1:
        return "same_place"
    transport_areas = {stop.transport_area_id for stop in stops}
    if None not in transport_areas and len(transport_areas) == 1:
        return "same_transport_hub"
    pair_distances = [
        haversine_km(first.coordinate, second.coordinate)
        for index, first in enumerate(stops)
        for second in stops[index + 1 :]
    ]
    if pair_distances and max(pair_distances) <= 0.5:
        return "nearby_separate_stores"
    return "separate_stops"


def route_distance_km(
    origin: Coordinate,
    destination: Coordinate,
    stops: tuple[Hub, ...],
) -> float:
    points = (origin,) + tuple(stop.coordinate for stop in stops) + (destination,)
    return sum(haversine_km(points[index], points[index + 1]) for index in range(len(points) - 1))


def straight_line_detour_km(
    origin: Coordinate,
    destination: Coordinate,
    stops: tuple[Hub, ...],
) -> float:
    baseline = haversine_km(origin, destination)
    orders = permutations(stops) if len(stops) > 1 else (stops,)
    shortest = min(route_distance_km(origin, destination, tuple(order)) for order in orders)
    return max(0.0, shortest - baseline)


def transit_access_rank_km(
    candidate: CandidateOption,
    geometry: tuple[Coordinate, ...],
) -> float:
    """Approximate what a stop costs on the network, not on the chord.

    `straight_line_detour_km` measures deviation from the great-circle line
    between origin and destination. Nothing travels that line. On a rail-shaped
    network a stop 3 km off the chord but on the line you are already riding is
    cheaper than one 500 m off it that needs two transfers, so ranking by the
    chord routes the wrong four candidates and the real winner is never priced.

    This proxy instead charges each stop for leaving the baseline route, walked
    in both directions, plus the walk between the stop and its nearest transit
    node. Both terms are in kilometres, so they stay comparable, and both fall
    to zero for a stop sitting on the route beside a station.
    """
    if not geometry:
        return 0.0
    total = 0.0
    for stop in candidate.stops:
        total += 2 * distance_to_geometry_km(stop.coordinate, geometry)
        if stop.transport_node_distance_m is not None:
            total += stop.transport_node_distance_m / 1000
    return total


def prune_candidates(
    candidates: list[CandidateOption],
    origin: Coordinate,
    destination: Coordinate,
    max_candidates: int,
    max_detour_km: float,
    geometry: tuple[Coordinate, ...] = (),
) -> list[CandidateOption]:
    measured = [
        CandidateOption(
            stops=candidate.stops,
            required_categories=candidate.required_categories,
            consolidated=candidate.consolidated,
            straight_line_detour_km=straight_line_detour_km(origin, destination, candidate.stops),
            stop_category_assignments=candidate.stop_category_assignments,
            stop_relationship=candidate.stop_relationship,
            match_classification=candidate.match_classification,
            requested_categories=candidate.requested_categories,
            omitted_categories=candidate.omitted_categories,
            substituted_categories=candidate.substituted_categories,
        )
        for candidate in candidates
    ]
    # The chord distance stays the hard reachability cap - it is the cheap,
    # conservative bound. Ordering within that cap is by network cost, so the
    # candidates that survive truncation are the ones worth a routing call.
    measured.sort(
        key=lambda candidate: (
            round(transit_access_rank_km(candidate, geometry), 3),
            candidate.straight_line_detour_km,
            len(candidate.stops),
            tuple(stop.id for stop in candidate.stops),
        )
    )
    within_limit = [candidate for candidate in measured if candidate.straight_line_detour_km <= max_detour_km]
    pool = within_limit if within_limit else measured
    chosen = pool[:max_candidates]
    # A stop beside where you start or finish is the obvious answer, and the
    # corridor proxy can still rank it out: Waterway Point, 400 m from Punggol
    # MRT, lost its slot to malls sitting directly on the NE line and was
    # never priced. The best such option at each end always gets routed.
    reserved: list[CandidateOption] = []
    for endpoint in (origin, destination):
        beside = [
            candidate for candidate in pool
            if all(haversine_km(endpoint, stop.coordinate) <= ENDPOINT_RESERVE_KM for stop in candidate.stops)
        ]
        if not beside:
            continue
        best = min(
            beside,
            key=lambda candidate: (
                len(candidate.stops),
                max(haversine_km(endpoint, stop.coordinate) for stop in candidate.stops),
                tuple(stop.id for stop in candidate.stops),
            ),
        )
        if best not in reserved:
            reserved.append(best)
    for best in reserved:
        if best in chosen or max_candidates < 2:
            continue
        replaceable = [index for index, candidate in enumerate(chosen) if candidate not in reserved]
        if len(chosen) < max_candidates:
            chosen.append(best)
        elif replaceable:
            chosen[replaceable[-1]] = best
    return chosen


# A stop this close to the origin or destination is always routed (see above).
ENDPOINT_RESERVE_KM = 1.0
