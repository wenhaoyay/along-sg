"""Run the curated, deterministic Singapore discovery behavior corpus."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import HubRepository
from app.discovery_models import DiscoveryConfidence, DiscoverySource, ResolvedPlace
from app.domain import Coordinate
from app.providers.mock import MockOneMapProvider
from app.providers.place_search import MockLivePlaceSearchProvider
from app.services.discovery import LocationResolver, NeedResolver


async def evaluate(database: Path, corpus_path: Path) -> dict:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    repo = HubRepository(database)
    repo.initialize()
    molly = ResolvedPlace(
        display_name="Molly Tea", coordinate=Coordinate(1.3004, 103.8390),
        address="Somerset, Singapore", category="Bubble tea shop",
        source=DiscoverySource.MOCK_LIVE, confidence=DiscoveryConfidence.LIKELY,
        provenance=(DiscoverySource.MOCK_LIVE,),
    )
    live = MockLivePlaceSearchProvider({
        "molly tea singapore": [molly], "mollytea singapore": [molly],
    })
    locations = LocationResolver(repo, MockOneMapProvider())
    needs = NeedResolver(repo, live)
    results: list[dict] = []
    latencies: list[float] = []
    wrong = ambiguous = unresolved = exact_local = fuzzy_local = semantic = live_count = 0
    for case in corpus["locations"]:
        started = time.perf_counter()
        matches = await locations.resolve(case["query"])
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        top = matches[0] if matches else None
        expected = case.get("expected_entity") or case.get("expected_contains")
        passed = bool(top and expected.casefold() in top.display_name.casefold())
        wrong += int(bool(top) and not passed)
        unresolved += int(not top)
        ambiguous += int(bool(top) and top.confidence == DiscoveryConfidence.AMBIGUOUS)
        exact_local += int(bool(top) and top.source == DiscoverySource.LTA_GAZETTEER and top.confidence == DiscoveryConfidence.EXACT)
        fuzzy_local += int(bool(top) and top.source == DiscoverySource.LTA_GAZETTEER and top.confidence == DiscoveryConfidence.STRONG)
        results.append({"kind":"location", "query":case["query"], "actual":top.display_name if top else None, "confidence":top.confidence.value if top else "unresolved", "passed":passed, "latency_ms":round(elapsed,2)})
    for case in corpus["needs"]:
        result = await needs.resolve(case["query"], allow_live=case.get("allow_live", True))
        latencies.append(result.latency_ms)
        expected_types = set(case.get("expected_any", [case.get("expected_type")]))
        passed = result.semantic_type.value in expected_types
        if case.get("expected_confidence"):
            passed = passed and result.confidence.value == case["expected_confidence"]
        wrong += int(not passed and result.confidence not in {DiscoveryConfidence.UNRESOLVED, DiscoveryConfidence.AMBIGUOUS})
        unresolved += int(result.confidence == DiscoveryConfidence.UNRESOLVED)
        ambiguous += int(result.confidence == DiscoveryConfidence.AMBIGUOUS)
        semantic += int(result.canonical_concept is not None)
        live_count += int(result.live_fallback_used)
        results.append({"kind":"need", "query":case["query"], "actual":result.semantic_type.value, "confidence":result.confidence.value, "place_count":len(result.places), "live":result.live_fallback_used, "passed":passed, "latency_ms":result.latency_ms})
    ordered = sorted(latencies)
    total = len(results)
    passed_total = sum(int(item["passed"]) for item in results)
    return {
        "corpus_cases": total, "passed": passed_total, "behavior_accuracy": round(passed_total / total, 4),
        "exact_local_resolution_rate": round(exact_local / total, 4),
        "fuzzy_local_resolution_rate": round(fuzzy_local / total, 4),
        "semantic_resolution_rate": round(semantic / total, 4),
        "live_fallback_rate": round(live_count / total, 4),
        "unresolved_rate": round(unresolved / total, 4),
        "wrong_resolution_rate": round(wrong / total, 4),
        "ambiguity_rate": round(ambiguous / total, 4),
        "average_latency_ms": round(statistics.mean(latencies), 2),
        "p95_latency_ms": round(ordered[min(len(ordered)-1, int(len(ordered)*0.95))], 2),
        "live_provider_request_count": live.calls,
        "live_cache_hit_rate": round(live.cache_hits / max(1, live.calls + live.cache_hits), 4),
        "source_distribution": needs.metrics_snapshot()["source_distribution"],
        "results": results,
        "disclaimer": "Curated-corpus behavior only; not universal real-world accuracy.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "discovery-evaluation.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.database, args.corpus))
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
