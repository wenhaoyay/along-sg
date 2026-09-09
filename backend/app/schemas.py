from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.intent_models import IntentV1
from app.discovery_models import OpenNeed


class CoordinateModel(BaseModel):
    latitude: float = Field(ge=1.1, le=1.5)
    longitude: float = Field(ge=103.5, le=104.1)


class LocationInput(BaseModel):
    query: str | None = Field(default=None, min_length=2, max_length=160)
    coordinate: CoordinateModel | None = None

    @model_validator(mode="after")
    def exactly_one_location_form(self) -> "LocationInput":
        if (self.query is None) == (self.coordinate is None):
            raise ValueError("Provide exactly one of query or coordinate")
        return self


class JourneyRequest(BaseModel):
    origin: LocationInput
    destination: LocationInput
    departure: datetime | None = None


class OptimizeRequest(JourneyRequest):
    errands: list[str] = Field(min_length=1, max_length=2)


class IntentParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    correction: bool = False
    origin: "ResolvedLocationContext | None" = None
    destination: "ResolvedLocationContext | None" = None


class ResolvedLocationContext(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    coordinate: CoordinateModel


class ConfirmedDiscoveryPlace(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    coordinate: CoordinateModel
    category: str = Field(min_length=2, max_length=64)
    address: str | None = Field(default=None, max_length=240)


class IntentOptimizeRequest(JourneyRequest):
    intent: IntentV1
    confirmed_discovery_places: list[ConfirmedDiscoveryPlace] = Field(default_factory=list, max_length=2)


class CoordinateResponse(BaseModel):
    latitude: float
    longitude: float


class GeocodeResultResponse(BaseModel):
    label: str
    coordinate: CoordinateResponse
    postal_code: str | None = None
    address: str | None = None
    entity_type: str = "place"
    confirmed: bool = True
    confidence: str = "likely"
    subtitle: str | None = None


class RouteLegResponse(BaseModel):
    mode: str
    duration_minutes: float
    distance_m: float
    from_name: str | None = None
    to_name: str | None = None
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    geometry_format: str | None = None
    route_short_name: str | None = None
    route_long_name: str | None = None
    agency: str | None = None
    stop_count: int | None = None
    segment_index: int | None = None


class RouteResponse(BaseModel):
    duration_minutes: float
    walking_minutes: float
    walking_distance_m: float
    transfers: int
    provider: str
    legs: list[RouteLegResponse]
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    dwell_minutes: float = 0
    time_dependent: bool | None = None
    geometry: list[CoordinateResponse] = Field(default_factory=list)


class GeocodeResponse(BaseModel):
    query: str
    results: list[GeocodeResultResponse]
    provider: str


class DiscoveryPlaceResponse(BaseModel):
    display_name: str
    coordinate: CoordinateResponse
    address: str | None = None
    mall_or_hub: str | None = None
    category: str | None = None
    confidence: str
    evidence: list[str] = Field(default_factory=list)
    evidence_tier: str = "supported"
    suitability: str = "business_verified"
    provenance: list[str] = Field(default_factory=list)


class NeedDiscoveryResponse(BaseModel):
    query: str
    semantic_type: str
    canonical_concept: str | None = None
    category: str | None = None
    confidence: str
    related_terms: list[str] = Field(default_factory=list)
    places: list[DiscoveryPlaceResponse] = Field(default_factory=list)
    live_fallback_used: bool = False
    live_provider_failed: bool = False
    clarification: str | None = None
    discovery_calls: int = 0
    cache_hits: int = 0
    latency_ms: float = 0
    open_need: OpenNeed | None = None
    provider_calls: dict[str, int] = Field(default_factory=dict)
    provider_latency_ms: dict[str, float] = Field(default_factory=dict)
    web_fallback_used: bool = False
    grounding_calls: int = 0
    warnings: list[str] = Field(default_factory=list)


class JourneyResponse(BaseModel):
    origin: GeocodeResultResponse
    destination: GeocodeResultResponse
    route: RouteResponse


class StopResponse(BaseModel):
    name: str
    display_name: str
    coordinate: CoordinateResponse
    matching_outlets: list[str]
    businesses: list["DisplayBusinessResponse"]
    semantic_type: str
    location_context: str
    context_kind: str
    location_quality: float = Field(ge=0, le=1)
    navigation_ready: bool = True
    arrival_time: datetime | None = None


class DisplayBusinessResponse(BaseModel):
    display_name: str
    canonical_brand: str | None = None
    category_labels: list[str]
    location_context: str | None = None
    opening_status: str = "unknown"


class DwellAllowanceResponse(BaseModel):
    label: str
    minutes: float


class DetourBreakdownResponse(BaseModel):
    extra_transport_minutes: float
    dwell_minutes: float
    dwell_allowances: list[DwellAllowanceResponse]
    total_incremental_minutes: float
    precision_note: str


class RecommendationResponse(BaseModel):
    time_dependent: bool = False
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    label: str
    stops: list[StopResponse]
    consolidated: bool
    total_duration_minutes: float
    total_walking_minutes: float
    total_walking_distance_m: float
    total_transfers: int
    incremental_detour_minutes: float
    incremental_walking_minutes: float
    incremental_walking_distance_m: float = 0
    incremental_transfers: int
    inconvenience_score: float
    dwell_minutes: float
    routed_segment_count: int
    stop_relationship: str
    explanation: str
    why_this_wins: str
    match_classification: str = "best_match"
    quality_label: str = "Best option"
    hard_constraints_satisfied: bool = True
    detour_breakdown: DetourBreakdownResponse
    route_geometry: list[CoordinateResponse] = Field(default_factory=list)
    legs: list[RouteLegResponse] = Field(default_factory=list)
    # Whether the app puts this forward as a choice, as opposed to reporting it
    # as something it routed and rejected. Both are full recommendations,
    # because you can select either - a compared option needs its own legs and
    # geometry the moment you pick it, and at that point the only difference
    # between the two is whether the app volunteered it.
    offered: bool = True


class CatalogCategoryResponse(BaseModel):
    slug: str
    name: str
    parent_slug: str | None = None
    outlet_count: int


class CatalogSearchResultResponse(BaseModel):
    display_name: str
    kind: Literal["category", "brand", "place"]
    canonical_brand: str | None = None
    categories: list[str]
    outlet_count: int
    example_location: str | None = None


class NearMissResponse(BaseModel):
    requested_category: str
    substitute_category: str
    stop_name: str
    approximate_straight_line_detour_km: float
    match_classification: str = "easier_alternative"
    explanation: str


class DiagnosticsResponse(BaseModel):
    generated_candidate_count: int
    pruned_candidate_count: int
    evaluated_candidate_count: int
    routing_call_count: int
    cache_hit_count: int
    provider_latency_ms: float
    optimization_latency_ms: float
    routing_soft_budget: int
    routing_hard_budget: int
    soft_budget_exceeded: bool
    hard_budget_reached: bool
    no_route_candidate_count: int
    time_aware_dwell_applied: bool
    departure_time_routing_verified: bool
    time_dependency_limitation: str | None = None
    raw_poi_count: int
    category_match_hub_count: int
    corridor_hub_count: int
    transit_proximity_hub_count: int
    hub_coverage_candidate_count: int
    approximate_detour_candidate_count: int
    routing_budget_candidate_count: int
    baseline_geometry_point_count: int
    excessive_detour_candidate_count: int
    near_miss_candidate_count: int
    outcome: str
    routing_concurrency: int


class OptimizeResponse(BaseModel):
    origin: GeocodeResultResponse
    destination: GeocodeResultResponse
    errands: list[str]
    baseline: RouteResponse
    recommendations: dict[str, RecommendationResponse]
    diagnostics: DiagnosticsResponse
    outcome: str = "ok"
    message: str | None = None
    data_attribution: str = "POI data © OpenStreetMap contributors, ODbL 1.0"
    intent: IntentV1 | None = None
    near_misses: list[NearMissResponse] = Field(default_factory=list)



class AnalyticsEventType(StrEnum):
    APP_OPENED = "app_opened"
    SEARCH_STARTED = "search_started"
    INTENT_PARSED = "intent_parsed"
    CLARIFICATION_REQUESTED = "clarification_requested"
    INTERPRETATION_CORRECTED = "interpretation_corrected"
    OPTIMIZATION_COMPLETED = "optimization_completed"
    OPTIMIZATION_FAILED = "optimization_failed"
    NO_CONVENIENT_OPTION = "no_convenient_option"
    RECOMMENDATION_VIEWED = "recommendation_viewed"
    RECOMMENDATION_SELECTED = "recommendation_selected"
    NAVIGATION_CLICKED = "navigation_clicked"
    ALTERNATIVE_SELECTED = "alternative_selected"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    TRIP_FEEDBACK_SUBMITTED = "trip_feedback_submitted"
    RETURN_USAGE = "return_usage"


class AnalyticsEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    anonymous_user_id: UUID
    session_id: UUID
    search_id: UUID | None = None
    event_type: AnalyticsEventType
    recommendation_key: Literal["best_overall", "fastest", "least_walking"] | None = None
    recommendation_rank: int | None = Field(default=None, ge=1, le=3)
    feedback_value: Literal[
        "positive", "negative", "roughly_accurate", "took_longer",
        "took_less_time", "did_not_make_trip",
    ] | None = None
    feedback_reason: Literal[
        "too_much_walking", "too_much_detour", "too_many_transfers",
        "bad_shop_location", "shop_closed", "misunderstood_request",
        "preferred_another_option", "other",
    ] | None = None
    parse_method: Literal["deterministic", "llm"] | None = None
    latency_ms: float | None = Field(default=None, ge=0, le=300_000)


class AnalyticsEventResponse(BaseModel):
    accepted: bool


class AnalyticsReportResponse(BaseModel):
    generated_at: datetime
    retention_days: int
    unique_anonymous_users: int
    searches: int
    searches_per_user: float
    completion_rate: float
    parse_correction_rate: float
    no_result_rate: float
    rank_one_acceptance_rate: float
    alternative_selection_rate: float
    navigation_click_rate: float
    positive_feedback: int
    negative_feedback: int
    common_negative_feedback_reasons: dict[str, int]
    median_optimization_latency_ms: float | None
    p95_optimization_latency_ms: float | None
    active_users_one_day: int
    active_users_seven_day: int
    returning_users: int
    return_usage_rate: float
    explicit_return_events: int
    event_counts: dict[str, int]
