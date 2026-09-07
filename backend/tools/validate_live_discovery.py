"""Run the explicitly gated V0.7.4 live discovery acceptance corpus.

The report contains normalized place evidence and aggregate counters only. Provider
keys, request headers, and raw proprietary payloads are never written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.discovery_models import DiscoverySearchContext, DiscoverySource, NeedSemanticType  # noqa: E402
from app.domain import Coordinate  # noqa: E402
from app.poi_ingestion import ingest_payload  # noqa: E402
from app.providers.place_search import (  # noqa: E402
    GeoapifyPlaceSearchProvider,
    TomTomPlaceSearchProvider,
)
from app.providers.web_search import TavilyWebDiscoveryProvider  # noqa: E402
from app.services.discovery import NeedResolver, contains_normalized_phrase  # noqa: E402


SIMPLE_CASES = (
    ("mee pok", "dish", ("mee pok", "bak chor mee"), ("noodle",)),
    ("fishball noodles", "dish", ("fishball",), ("noodle",)),
    ("cai fan", "dish", ("cai fan", "caifan", "economy rice"), ("food",)),
    ("hor fun", "dish", ("hor fun",), ("noodle",)),
    ("mala", "dish", ("mala", "ma la"), ("restaurant", "food")),
    ("prata", "dish", ("prata",), ("indian", "restaurant")),
    ("matcha", "dish", ("matcha",), ("cafe", "tea")),
    ("durian", "dish", ("durian",), ("fruit", "dessert")),
    ("Korean fried chicken", "dish", ("korean fried chicken",), ("korean", "chicken")),
    ("kaya toast", "dish", ("kaya",), ("toast", "coffee")),
    ("laksa", "dish", ("laksa",), ("noodle", "food")),
    ("ban mian", "dish", ("ban mian",), ("noodle",)),
    ("ramen", "dish", ("ramen",), ("japanese", "noodle")),
    ("sushi", "dish", ("sushi",), ("japanese",)),
    ("dim sum", "dish", ("dim sum",), ("chinese",)),
    ("Panadol", "product", ("panadol",), ("pharmacy", "chemist")),
    ("contact lens solution", "product", ("contact lens",), ("optical", "pharmacy")),
    ("cat litter", "product", ("cat litter",), ("pet", "animal")),
    ("USB-C cable", "product", ("usb-c", "usb c"), ("electronics", "computer", "mobile")),
    ("phone charger", "product", ("charger",), ("electronics", "mobile", "computer")),
    ("printer ink", "product", ("printer ink", "toner", "cartridge"), ("computer", "electronics", "printing")),
    ("umbrella", "product", ("umbrella",), ("department", "convenience", "variety")),
    ("mosquito repellent", "product", ("mosquito", "repellent"), ("pharmacy", "hardware")),
    ("bubble wrap", "product", ("bubble wrap",), ("packaging", "stationery", "hardware")),
    ("birthday candles", "product", ("birthday candle",), ("party", "bakery", "variety")),
    ("cat food", "product", ("cat food",), ("pet", "animal")),
    ("shoe glue", "product", ("shoe glue",), ("shoe repair", "hardware")),
    ("AA batteries", "product", ("battery", "batteries"), ("electronics", "convenience", "hardware")),
    ("travel adapter", "product", ("adapter",), ("electronics", "travel")),
    ("toothpaste", "product", ("toothpaste",), ("pharmacy", "supermarket", "convenience")),
    ("passport photo", "service", ("passport photo", "photo-me"), ("photo lab", "photography")),
    ("key duplication", "service", ("key duplication", "key cutting", "locksmith"), ("hardware", "repair")),
    ("haircut", "service", ("haircut",), ("hair", "barber", "salon")),
    ("optical shop", "service", ("optical", "optician"), ("eyewear",)),
    ("parcel drop-off", "service", ("parcel", "post office"), ("courier", "postal")),
    ("printing", "service", ("print", "printing"), ("copy", "stationery")),
    ("shoe repair", "service", ("shoe repair", "cobbler"), ("repair",)),
    ("photocopy", "service", ("photocopy",), ("printing", "copy")),
    ("ATM", "service", ("atm",), ("bank", "cash")),
    ("spectacles repair", "service", ("spectacle",), ("optical", "eyewear")),
    ("Molly Tea", "specific_business", ("molly tea", "mollytea"), ()),
    ("KFC", "specific_business", ("kfc", "kentucky fried chicken"), ()),
    ("Watsons", "specific_business", ("watsons",), ()),
    ("Starbucks", "specific_business", ("starbucks",), ()),
    ("313 Somerset", "specific_business", ("313@somerset", "313 somerset"), ()),
    ("Popular", "specific_business", ("popular bookstore", "popular"), ()),
    ("Guardian", "specific_business", ("guardian",), ()),
    ("Challenger", "specific_business", ("challenger",), ()),
    ("Toast Box", "specific_business", ("toast box",), ()),
    ("Old Chang Kee", "specific_business", ("old chang kee",), ()),
    ("Mister Mobile", "specific_business", ("mister mobile",), ()),
    ("Birds of Paradise Gelato", "specific_business", ("birds of paradise",), ()),
)

COMPOUND_CASES = (
    "mee pok and Panadol",
    "coffee and printer ink",
    "cat food and groceries",
    "flowers and birthday cake",
    "bubble tea and passport photo",
)


@dataclass(frozen=True)
class LabelledCase:
    query: str
    expected_type: str
    direct_terms: tuple[str, ...]
    category_terms: tuple[str, ...]


def relevance_label(case: LabelledCase, place) -> str:
    text = " ".join((place.display_name, place.category or "", *place.evidence))
    direct = any(contains_normalized_phrase(text, term) for term in case.direct_terms)
    category = any(contains_normalized_phrase(text, term) for term in case.category_terms)
    web_direct = any(
        item.source == DiscoverySource.TAVILY
        and any(contains_normalized_phrase(observed, case.query) for observed in item.observed_text)
        for item in place.structured_evidence
    )
    if case.expected_type in {"specific_business", "dish"}:
        return "GOOD" if direct else ("WEAK" if category else "WRONG")
    return "GOOD" if direct or category or web_direct else "WRONG"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * fraction)] if ordered else 0.0


async def run(output: Path) -> dict:
    settings = Settings.from_env()
    missing = [
        name for name, value in (
            ("TOMTOM_API_KEY", settings.tomtom_api_key),
            ("GEOAPIFY_API_KEY", settings.geoapify_api_key),
            ("TAVILY_API_KEY", settings.tavily_api_key),
        ) if not value
    ]
    if missing:
        raise SystemExit("Missing required live keys: " + ", ".join(missing))

    providers = (
        TomTomPlaceSearchProvider(
            settings.tomtom_api_key,
            settings.discovery_timeout_seconds,
            settings.discovery_cache_ttl_seconds,
            hard_budget=2,
            max_retries=settings.discovery_provider_max_retries,
        ),
        GeoapifyPlaceSearchProvider(
            settings.geoapify_api_key,
            settings.discovery_timeout_seconds,
            settings.discovery_cache_ttl_seconds,
            settings.discovery_provider_max_retries,
        ),
        TavilyWebDiscoveryProvider(settings.tavily_api_key, settings.discovery_timeout_seconds),
    )
    tomtom, geoapify, tavily = providers
    context = DiscoverySearchContext(
        center=Coordinate(1.3405, 103.8055),
        radius_m=18_000,
        route_geometry=(Coordinate(1.3827, 103.7624), Coordinate(1.3043, 103.8322)),
    )
    started = time.perf_counter()
    latencies: list[float] = []
    label_counts: Counter[str] = Counter()
    resolved = 0
    local_resolved = 0
    cases_out: list[dict] = []
    compounds_out: list[dict] = []

    try:
        work_root = BACKEND_ROOT.parent / "work"
        work_root.mkdir(parents=True, exist_ok=True)
        database_path = work_root / "v074-live-validation.db"
        repository = HubRepository(database_path)
        repository.initialize()
        osm_snapshot = BACKEND_ROOT / "data" / "singapore-osm-pois.json"
        if osm_snapshot.exists():
            ingest_payload(repository, json.loads(osm_snapshot.read_text(encoding="utf-8")))
        resolver = NeedResolver(
            repository,
            live_provider=tomtom,
            secondary_provider=geoapify,
            web_provider=tavily,
            primary_calls_per_need=1,
            secondary_calls_per_need=1,
            web_calls_per_need=1,
            grounding_candidate_limit=2,
        )
        for raw in SIMPLE_CASES:
            case = LabelledCase(raw[0], raw[1], raw[2], raw[3])
            result = await resolver.resolve(case.query, limit=3, allow_live=True, context=context)
            latencies.append(result.latency_ms)
            resolved += int(bool(result.places))
            local_resolved += int(bool(result.places) and not result.live_fallback_used)
            candidates = []
            for place in result.places[:3]:
                label = relevance_label(case, place)
                label_counts[label] += 1
                candidates.append({
                    "label": label,
                    "name": place.display_name,
                    "address": place.address,
                    "latitude": place.coordinate.latitude,
                    "longitude": place.coordinate.longitude,
                    "category": place.category,
                    "source": place.source.value,
                    "provenance": [item.value for item in place.provenance],
                    "evidence_tier": place.evidence_tier.value,
                    "web_evidence": [
                        item.observed_text[0] for item in place.structured_evidence
                        if item.source == DiscoverySource.TAVILY and item.observed_text
                    ],
                })
            cases_out.append({
                "query": case.query,
                "expected_type": case.expected_type,
                "actual_type": result.semantic_type.value,
                "resolved": bool(result.places),
                "source": result.source.value if result.source else None,
                "provider_calls": result.provider_calls,
                "provider_latency_ms": result.provider_latency_ms,
                "cache_hits": result.cache_hits,
                "latency_ms": result.latency_ms,
                "warning": result.warnings,
                "candidates": candidates,
            })

        for query in COMPOUND_CASES:
            needs = resolver.parse_open_needs(query)[:2]
            parts = [await resolver.resolve(
                need.raw_text, limit=3, allow_live=True, context=context, open_need=need,
            ) for need in needs]
            compounds_out.append({
                "query": query,
                "parts": [{
                    "query": part.original_query,
                    "resolved": bool(part.places),
                    "type": part.semantic_type.value,
                    "top_candidate": part.places[0].display_name if part.places else None,
                    "top_address": part.places[0].address if part.places else None,
                    "provider_calls": part.provider_calls,
                    "latency_ms": part.latency_ms,
                    "warnings": part.warnings,
                } for part in parts],
                "fully_resolved": len(parts) == 2 and all(part.places for part in parts),
                "partially_resolved": len(parts) == 2 and sum(bool(part.places) for part in parts) == 1,
            })

        metrics = resolver.metrics_snapshot()
    finally:
        for provider in providers:
            await provider.close()

    top1 = [item["candidates"][0]["label"] for item in cases_out if item["candidates"]]
    top3_cases = [item for item in cases_out if item["candidates"]]
    total_labels = sum(label_counts.values())
    report = {
        "schema_version": "v0.7.4-live-validation-1",
        "live_captured": True,
        "label_method": "automated lexical rubric; provisional, requires independent manual review",
        "acceptance_verified": False,
        "provider_configuration": {
            "tomtom": True, "geoapify": True, "tavily": True, "openai": False,
            "keys_recorded": False,
            "primary_calls_per_need": 1,
            "secondary_calls_per_need": 1,
            "web_calls_per_need": 1,
            "grounding_candidate_limit": 2,
            # Conservative upper bound: each TomTom search can perform two
            # attempts before a bounded fuzzy fallback; Geoapify has retries.
            # Include discovery and two business/location grounding leads.
            "theoretical_external_call_ceiling": (len(SIMPLE_CASES) + 2 * len(COMPOUND_CASES)) * 41,
        },
        "summary": {
            "simple_query_count": len(SIMPLE_CASES),
            "compound_query_count": len(COMPOUND_CASES),
            "simple_resolved": resolved,
            "full_ladder_zero_result_rate": 1 - (resolved / len(SIMPLE_CASES)),
            "local_resolution_share": local_resolved / len(SIMPLE_CASES),
            "top_1_good_rate": top1.count("GOOD") / len(top1) if top1 else 0,
            "top_1_weak_rate": top1.count("WEAK") / len(top1) if top1 else 0,
            "top_1_wrong_rate": top1.count("WRONG") / len(top1) if top1 else 0,
            "top_3_has_good_rate": sum(
                any(candidate["label"] == "GOOD" for candidate in item["candidates"])
                for item in top3_cases
            ) / len(top3_cases) if top3_cases else 0,
            "candidate_good_rate": label_counts["GOOD"] / total_labels if total_labels else 0,
            "candidate_weak_rate": label_counts["WEAK"] / total_labels if total_labels else 0,
            "candidate_wrong_rate": label_counts["WRONG"] / total_labels if total_labels else 0,
            "compound_full_resolution_rate": sum(item["fully_resolved"] for item in compounds_out) / len(compounds_out),
            "compound_partial_resolution_rate": sum(item["partially_resolved"] for item in compounds_out) / len(compounds_out),
            "latency_mean_ms": statistics.fmean(latencies),
            "latency_p50_ms": percentile(latencies, 0.5),
            "latency_p95_ms": percentile(latencies, 0.95),
            "total_elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "provider_calls": {"tomtom": tomtom.calls, "geoapify": geoapify.calls, "tavily": tavily.calls},
            "provider_latency_ms": {
                "tomtom": tomtom.latency_ms, "geoapify": geoapify.latency_ms, "tavily": tavily.latency_ms,
            },
            "cache_hits": metrics["cache_hits"],
        },
        "cases": cases_out,
        "compounds": compounds_out,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded live V0.7.4 discovery validation")
    parser.add_argument("--run-live", action="store_true", help="Required explicit external-call gate")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_live:
        raise SystemExit("Refusing live calls without --run-live")
    report = asyncio.run(run(args.output))
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
