from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.discovery_models import OpenNeed


class WalkingTolerance(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"


class TransferTolerance(StrEnum):
    NO_EXTRA = "no_extra"
    PREFER_FEWER = "prefer_fewer"
    STANDARD = "standard"


class Urgency(StrEnum):
    NORMAL = "normal"
    SOON = "soon"
    URGENT = "urgent"


class ParseMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"


class IntentStatus(StrEnum):
    RESOLVED = "resolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNRESOLVED = "unresolved"


class RecommendationClassification(StrEnum):
    BEST_MATCH = "best_match"
    EXACT_MATCH = "exact_match"
    CLOSEST_EXACT = "closest_exact"
    BEST_AVAILABLE = "best_available"
    EASIER_ALTERNATIVE = "easier_alternative"
    PARTIAL_OPTION = "partial_option"
    EXCEEDS_LIMIT = "exceeds_limit"


class IntentErrand(BaseModel):
    category: str = Field(min_length=2, max_length=64)
    required: bool = True
    exact_brand: str | None = Field(default=None, min_length=1, max_length=80)
    preferred_brand: str | None = Field(default=None, min_length=1, max_length=80)
    exact_place: str | None = Field(default=None, min_length=1, max_length=120)
    substitutes_allowed: bool = True
    discovery_concept: str | None = Field(default=None, min_length=1, max_length=80)
    open_need: OpenNeed | None = None
    discovery_category: str | None = Field(default=None, min_length=2, max_length=64)

    @model_validator(mode="after")
    def hard_brand_cannot_allow_substitution(self) -> "IntentErrand":
        if self.exact_brand and self.substitutes_allowed:
            raise ValueError("An exact required brand cannot allow substitutes")
        if self.exact_brand and self.preferred_brand:
            raise ValueError("Use either exact_brand or preferred_brand, not both")
        if self.exact_place and (self.exact_brand or self.preferred_brand):
            raise ValueError("Use either exact_place or a brand preference")
        if self.category.startswith("open_") and self.open_need is None:
            raise ValueError("Open-world categories require an OpenNeed")
        return self


class JourneyMention(BaseModel):
    endpoint: Literal["origin", "destination"]
    text: str
    resolved_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class JourneyConflict(BaseModel):
    endpoint: Literal["origin", "destination"]
    current_label: str
    mentioned_text: str
    mentioned_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reason: str


class IntentPreferences(BaseModel):
    max_detour_minutes: float | None = Field(default=None, ge=0, le=180)
    walking_tolerance: WalkingTolerance = WalkingTolerance.STANDARD
    max_extra_walking_minutes: float | None = Field(default=None, ge=0, le=120)
    transfer_tolerance: TransferTolerance = TransferTolerance.STANDARD
    max_additional_transfers: int | None = Field(default=None, ge=0, le=5)
    prefer_consolidated_stops: bool = False
    urgency: Urgency = Urgency.NORMAL
    arrival_by: datetime | None = None
    max_detour_is_hard: bool = False
    max_extra_walking_is_hard: bool = False
    max_additional_transfers_is_hard: bool = False


class IntentV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    original_text: str = Field(min_length=1, max_length=500)
    required_errands: list[IntentErrand] = Field(default_factory=list, max_length=2)
    optional_errands: list[IntentErrand] = Field(default_factory=list, max_length=2)
    preferences: IntentPreferences = Field(default_factory=IntentPreferences)
    parse_method: ParseMethod = ParseMethod.DETERMINISTIC
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_errand_scope(self) -> "IntentV1":
        errands = self.required_errands + self.optional_errands
        if not errands:
            raise ValueError("At least one errand is required")
        if len(errands) > 2:
            raise ValueError("V0.6 supports at most two total errands")
        categories = [item.category for item in errands]
        if len(categories) != len(set(categories)):
            raise ValueError("Each errand category must be distinct")
        if any(not item.required for item in self.required_errands):
            raise ValueError("required_errands entries must have required=true")
        if any(item.required for item in self.optional_errands):
            raise ValueError("optional_errands entries must have required=false")
        return self


class IntentParseDiagnostics(BaseModel):
    parser_latency_ms: float = 0
    llm_latency_ms: float = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    validation_failures: int = 0
    unresolved_brands: list[str] = Field(default_factory=list)
    unresolved_categories: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    clarification_required: bool = False
    correction_applied: bool = False


class IntentParseResponse(BaseModel):
    status: IntentStatus
    intent: IntentV1 | None = None
    unresolved_terms: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    diagnostics: IntentParseDiagnostics
    journey_mentions: list[JourneyMention] = Field(default_factory=list)
    journey_conflicts: list[JourneyConflict] = Field(default_factory=list)


class IntentMetricsSnapshot(BaseModel):
    total_parses: int
    deterministic_parses: int
    llm_parses: int
    deterministic_parse_rate: float
    llm_parse_rate: float
    validation_failures: int
    unresolved_terms: int
    fallbacks: int
    fallback_rate: float
    clarifications: int
    clarification_rate: float
    corrections: int
    near_miss_alternatives_selected: int
    parser_latency_ms_total: float
    llm_latency_ms_total: float
    input_tokens: int
    output_tokens: int
    measured_cost_usd: float | None = None
