from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ScoringWeights:
    detour: float = 1.0
    walking: float = 0.65
    transfer: float = 6.0
    preferred_brand_bonus: float = 2.0
    consolidated_stop_bonus: float = 1.0
    data_quality_bonus: float = 2.5


@dataclass(frozen=True)
class DwellTimes:
    groceries: float = 20.0
    pharmacy: float = 10.0
    parcel: float = 8.0
    electronics: float = 15.0
    banking: float = 15.0
    fast_food: float = 15.0
    fried_chicken: float = 15.0
    bubble_tea: float = 8.0
    coffee: float = 12.0
    convenience: float = 5.0
    restaurants: float = 30.0
    burgers: float = 20.0
    japanese_food: float = 30.0
    korean_food: float = 30.0
    chinese_food: float = 30.0
    bakeries: float = 8.0
    dessert: float = 12.0
    stationery: float = 10.0
    hardware: float = 15.0
    florists: float = 10.0
    pet_supplies: float = 15.0
    clothing: float = 20.0
    household: float = 20.0
    printing: float = 10.0
    haircuts: float = 30.0
    optical: float = 20.0
    repairs: float = 20.0

    def for_categories(self, categories: tuple[str, ...]) -> float:
        return sum(float(getattr(self, category, 10.0 if category.startswith("open_") else 0.0)) for category in categories)


@dataclass(frozen=True)
class Settings:
    onemap_mock: bool = True
    onemap_email: str | None = None
    onemap_password: str | None = None
    onemap_base_url: str = "https://www.onemap.gov.sg"
    onemap_timeout_seconds: float = 15.0
    token_refresh_margin_seconds: int = 300
    onemap_max_retries: int = 2
    onemap_retry_backoff_seconds: float = 0.2
    onemap_departure_time_routing_verified: bool = True
    database_path: Path = Path(__file__).resolve().parents[1] / "data" / "errands.db"
    scoring: ScoringWeights = ScoringWeights()
    dwell_times: DwellTimes = DwellTimes()
    max_candidates: int = 6
    max_straight_line_detour_km: float = 12.0
    max_reasonable_detour_minutes: float = 45.0
    candidate_corridor_km: float = 2.5
    candidate_endpoint_radius_km: float = 2.0
    candidate_max_transit_node_distance_m: float = 1200.0
    candidate_max_hubs_per_category: int = 8
    routing_soft_budget: int = 16
    routing_hard_budget: int = 20
    route_cache_max_entries: int = 512
    route_cache_ttl_seconds: float = 300.0
    route_cache_departure_bucket_minutes: int = 1
    routing_concurrency: int = 4
    llm_intent_enabled: bool = False
    openai_api_key: str | None = None
    openai_intent_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 20.0
    # LTA DataMall. Free, 10 million calls a day, and served under the
    # Singapore Open Data Licence - so unlike the place providers weighed up
    # for opening hours, its data may be stored and served onward.
    lta_account_key: str | None = None
    datamall_mock: bool = True
    datamall_timeout_seconds: float = 8.0
    tomtom_api_key: str | None = None
    geoapify_api_key: str | None = None
    tavily_api_key: str | None = None
    discovery_live_enabled: bool = False
    discovery_web_enabled: bool = False
    discovery_semantic_llm_enabled: bool = False
    discovery_timeout_seconds: float = 5.0
    discovery_cache_ttl_seconds: float = 300.0
    discovery_hard_budget: int = 3
    discovery_provider_max_retries: int = 1
    discovery_primary_calls_per_need: int = 2
    discovery_secondary_calls_per_need: int = 1
    discovery_web_calls_per_need: int = 1
    discovery_grounding_candidate_limit: int = 4
    discovery_gap_telemetry_enabled: bool = False
    analytics_database_path: Path = Path(__file__).resolve().parents[1] / "data" / "analytics.db"
    analytics_retention_days: int = 90
    beta_admin_token: str | None = None
    optimization_timeout_seconds: float = 45.0
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:3000", "http://127.0.0.1:3000"
    )
    serve_frontend_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            onemap_mock=_bool_env("ONEMAP_MOCK", True),
            lta_account_key=os.getenv("LTA_ACCOUNT_KEY") or None,
            datamall_mock=_bool_env("DATAMALL_MOCK", True),
            datamall_timeout_seconds=float(os.getenv("DATAMALL_TIMEOUT_SECONDS", "8")),
            onemap_email=os.getenv("ONEMAP_EMAIL") or os.getenv("ONEMAP_API_EMAIL"),
            onemap_password=os.getenv("ONEMAP_PASSWORD") or os.getenv("ONEMAP_API_PASSWORD"),
            onemap_base_url=os.getenv("ONEMAP_BASE_URL", "https://www.onemap.gov.sg").rstrip("/"),
            onemap_timeout_seconds=float(os.getenv("ONEMAP_TIMEOUT_SECONDS", "15")),
            token_refresh_margin_seconds=int(
                os.getenv("ONEMAP_TOKEN_REFRESH_MARGIN_SECONDS", "300")
            ),
            onemap_max_retries=int(os.getenv("ONEMAP_MAX_RETRIES", "2")),
            onemap_retry_backoff_seconds=float(
                os.getenv("ONEMAP_RETRY_BACKOFF_SECONDS", "0.2")
            ),
            onemap_departure_time_routing_verified=_bool_env(
                "ONEMAP_DEPARTURE_TIME_ROUTING_VERIFIED", True
            ),
            database_path=Path(
                os.getenv(
                    "DATABASE_PATH",
                    str(Path(__file__).resolve().parents[1] / "data" / "errands.db"),
                )
            ),
            scoring=ScoringWeights(
                detour=float(os.getenv("OPTIMIZER_DETOUR_WEIGHT", "1.0")),
                walking=float(os.getenv("OPTIMIZER_WALK_WEIGHT", "0.65")),
                transfer=float(os.getenv("OPTIMIZER_TRANSFER_WEIGHT", "6.0")),
                preferred_brand_bonus=float(
                    os.getenv("OPTIMIZER_PREFERRED_BRAND_BONUS", "2.0")
                ),
                consolidated_stop_bonus=float(
                    os.getenv("OPTIMIZER_CONSOLIDATED_STOP_BONUS", "1.0")
                ),
                data_quality_bonus=float(
                    os.getenv("OPTIMIZER_DATA_QUALITY_BONUS", "2.5")
                ),
            ),
            dwell_times=DwellTimes(
                groceries=float(os.getenv("DWELL_GROCERIES_MINUTES", "20")),
                pharmacy=float(os.getenv("DWELL_PHARMACY_MINUTES", "10")),
                parcel=float(os.getenv("DWELL_PARCEL_MINUTES", "8")),
                electronics=float(os.getenv("DWELL_ELECTRONICS_MINUTES", "15")),
                banking=float(os.getenv("DWELL_BANKING_MINUTES", "15")),
                fast_food=float(os.getenv("DWELL_FAST_FOOD_MINUTES", "15")),
                fried_chicken=float(os.getenv("DWELL_FRIED_CHICKEN_MINUTES", "15")),
                bubble_tea=float(os.getenv("DWELL_BUBBLE_TEA_MINUTES", "8")),
                coffee=float(os.getenv("DWELL_COFFEE_MINUTES", "12")),
                convenience=float(os.getenv("DWELL_CONVENIENCE_MINUTES", "5")),
            ),
            max_candidates=int(os.getenv("OPTIMIZER_MAX_CANDIDATES", "6")),
            max_straight_line_detour_km=float(
                os.getenv("OPTIMIZER_MAX_STRAIGHT_LINE_DETOUR_KM", "12")
            ),
            max_reasonable_detour_minutes=float(
                os.getenv("OPTIMIZER_MAX_REASONABLE_DETOUR_MINUTES", "45")
            ),
            candidate_corridor_km=float(os.getenv("OPTIMIZER_CORRIDOR_KM", "2.5")),
            candidate_endpoint_radius_km=float(
                os.getenv("OPTIMIZER_ENDPOINT_RADIUS_KM", "2.0")
            ),
            candidate_max_transit_node_distance_m=float(
                os.getenv("OPTIMIZER_MAX_TRANSIT_NODE_DISTANCE_M", "1200")
            ),
            candidate_max_hubs_per_category=int(
                os.getenv("OPTIMIZER_MAX_HUBS_PER_CATEGORY", "8")
            ),
            routing_soft_budget=int(os.getenv("OPTIMIZER_ROUTING_SOFT_BUDGET", "16")),
            routing_hard_budget=int(os.getenv("OPTIMIZER_ROUTING_HARD_BUDGET", "20")),
            route_cache_max_entries=int(os.getenv("ROUTE_CACHE_MAX_ENTRIES", "512")),
            route_cache_ttl_seconds=float(os.getenv("ROUTE_CACHE_TTL_SECONDS", "300")),
            route_cache_departure_bucket_minutes=int(
                os.getenv("ROUTE_CACHE_DEPARTURE_BUCKET_MINUTES", "1")
            ),
            routing_concurrency=int(os.getenv("OPTIMIZER_ROUTING_CONCURRENCY", "4")),
            llm_intent_enabled=_bool_env("LLM_INTENT_ENABLED", False),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_intent_model=os.getenv("OPENAI_INTENT_MODEL", "gpt-4.1-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20")),
            tomtom_api_key=os.getenv("TOMTOM_API_KEY"),
            geoapify_api_key=os.getenv("GEOAPIFY_API_KEY"),
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            discovery_live_enabled=_bool_env("DISCOVERY_LIVE_ENABLED", False),
            discovery_web_enabled=_bool_env("DISCOVERY_WEB_ENABLED", False),
            discovery_semantic_llm_enabled=_bool_env("DISCOVERY_SEMANTIC_LLM_ENABLED", False),
            discovery_timeout_seconds=float(os.getenv("DISCOVERY_TIMEOUT_SECONDS", "5")),
            discovery_cache_ttl_seconds=float(os.getenv("DISCOVERY_CACHE_TTL_SECONDS", "300")),
            discovery_hard_budget=int(os.getenv("DISCOVERY_HARD_BUDGET", "3")),
            discovery_provider_max_retries=int(os.getenv("DISCOVERY_PROVIDER_MAX_RETRIES", "1")),
            discovery_primary_calls_per_need=int(os.getenv("DISCOVERY_PRIMARY_CALLS_PER_NEED", "2")),
            discovery_secondary_calls_per_need=int(os.getenv("DISCOVERY_SECONDARY_CALLS_PER_NEED", "1")),
            discovery_web_calls_per_need=int(os.getenv("DISCOVERY_WEB_CALLS_PER_NEED", "1")),
            discovery_grounding_candidate_limit=int(os.getenv("DISCOVERY_GROUNDING_CANDIDATE_LIMIT", "4")),
            discovery_gap_telemetry_enabled=_bool_env("DISCOVERY_GAP_TELEMETRY_ENABLED", False),
            analytics_database_path=Path(
                os.getenv(
                    "ANALYTICS_DATABASE_PATH",
                    str(Path(__file__).resolve().parents[1] / "data" / "analytics.db"),
                )
            ),
            analytics_retention_days=int(os.getenv("ANALYTICS_RETENTION_DAYS", "90")),
            beta_admin_token=os.getenv("BETA_ADMIN_TOKEN"),
            optimization_timeout_seconds=float(
                os.getenv("OPTIMIZATION_TIMEOUT_SECONDS", "45")
            ),
            cors_allowed_origins=tuple(
                item.strip()
                for item in os.getenv(
                    "CORS_ALLOWED_ORIGINS",
                    "http://localhost:3000,http://127.0.0.1:3000",
                ).split(",")
                if item.strip()
            ),
            serve_frontend_dir=(
                Path(os.environ["SERVE_FRONTEND_DIR"])
                if os.getenv("SERVE_FRONTEND_DIR")
                else None
            ),
        )
