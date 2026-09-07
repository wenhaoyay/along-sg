from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class GeocodeMatch:
    label: str
    coordinate: Coordinate
    postal_code: str | None = None
    address: str | None = None
    entity_type: str = "place"


@dataclass(frozen=True)
class RouteLeg:
    mode: str
    duration_minutes: float
    distance_m: float
    from_name: str | None = None
    to_name: str | None = None
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    geometry: str | None = None
    geometry_format: str | None = None


@dataclass(frozen=True)
class RouteResult:
    duration_minutes: float
    walking_minutes: float
    walking_distance_m: float
    transfers: int
    legs: tuple[RouteLeg, ...] = ()
    provider: str = "unknown"
    source_schema: str = "normalized-v1"
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    dwell_minutes: float = 0.0
    time_dependent: bool | None = None


@dataclass(frozen=True)
class Store:
    name: str
    category: str
    canonical_brand: str | None = None
    categories: tuple[str, ...] = ()
    opening_hours: str | None = None
    closure_status: str = "unknown"
    source: str = "curated"
    source_id: str | None = None

    @property
    def all_categories(self) -> frozenset[str]:
        return frozenset((self.category, *self.categories))


@dataclass(frozen=True)
class Hub:
    id: int
    name: str
    coordinate: Coordinate
    stores: tuple[Store, ...]
    semantic_type: str = "standalone"
    transport_area_id: str | None = None
    consolidation_group_id: str | None = None
    source: str = "curated"
    source_id: str | None = None
    last_verified_at: datetime | None = None
    opening_hours: str | None = None
    closure_status: str = "unknown"
    transport_node_distance_m: float | None = None
    address: str | None = None
    transport_node_name: str | None = None
    nearby_context_name: str | None = None
    nearby_context_distance_m: float | None = None

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(
            category for store in self.stores for category in store.all_categories
        )


@dataclass(frozen=True)
class NearMissCandidate:
    requested_category: str
    substitute_category: str
    hub: Hub
    approximate_detour_km: float


@dataclass(frozen=True)
class CandidateOption:
    stops: tuple[Hub, ...]
    required_categories: tuple[str, ...]
    consolidated: bool
    straight_line_detour_km: float = 0.0
    stop_category_assignments: tuple[tuple[int, tuple[str, ...]], ...] = ()
    stop_relationship: str = "single_stop"
    match_classification: str = "best_match"
    requested_categories: tuple[str, ...] = ()
    omitted_categories: tuple[str, ...] = ()
    substituted_categories: tuple[tuple[str, str], ...] = ()

    def categories_at(self, hub_id: int) -> tuple[str, ...]:
        for assigned_hub_id, categories in self.stop_category_assignments:
            if assigned_hub_id == hub_id:
                return categories
        return self.required_categories if len(self.stops) == 1 else ()


@dataclass(frozen=True)
class ScoredCandidate:
    # Per-stop estimated arrival, kept separate from the combined journey.
    option: CandidateOption
    ordered_stops: tuple[Hub, ...]
    total_route: RouteResult
    incremental_detour_minutes: float
    incremental_walking_minutes: float
    incremental_transfers: int
    overall_score: float
    incremental_walking_distance_m: float = 0.0
    routed_segment_count: int = 0
    explanation: str = ""
    match_classification: str = "best_match"
    data_quality_score: float = 0.0
    hard_constraints_satisfied: bool = True
    stop_arrivals: tuple[datetime | None, ...] = ()
    stop_dwell_minutes: tuple[float, ...] = ()


@dataclass(frozen=True)
class OptimizationPreferences:
    exact_brands: tuple[tuple[str, str], ...] = ()
    exact_places: tuple[tuple[str, str], ...] = ()
    preferred_brands: tuple[tuple[str, str], ...] = ()
    max_detour_minutes: float | None = None
    max_extra_walking_minutes: float | None = None
    max_additional_transfers: int | None = None
    prefer_consolidated_stops: bool = False
    detour_weight_multiplier: float = 1.0
    walking_weight_multiplier: float = 1.0
    transfer_weight_multiplier: float = 1.0
    arrival_by: datetime | None = None
    max_detour_is_hard: bool = False
    max_extra_walking_is_hard: bool = False
    max_additional_transfers_is_hard: bool = False


@dataclass(frozen=True)
class CandidateFallback:
    categories: tuple[str, ...]
    match_classification: str
    requested_categories: tuple[str, ...]
    omitted_categories: tuple[str, ...] = ()
    substituted_categories: tuple[tuple[str, str], ...] = ()
    exact_brands: tuple[tuple[str, str], ...] = ()
    exact_places: tuple[tuple[str, str], ...] = ()
