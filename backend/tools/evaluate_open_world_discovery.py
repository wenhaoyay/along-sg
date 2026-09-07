from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import HubRepository
from app.poi_ingestion import ingest_payload
from app.services.discovery import NeedResolver


DATA = Path(__file__).resolve().parents[1] / "data" / "open-world-evaluation.json"


def corpus(payload: dict) -> list[dict]:
    cases: list[dict] = []
    for expected_type, terms in payload["groups"].items():
        for term in terms:
            for template in payload["templates"]:
                cases.append({"query": template.format(term=term), "plausible": True, "expected_type": expected_type})
    cases.extend({"query": value, "plausible": True, "expected_type": None} for value in payload["colloquial"])
    cases.extend({"query": value, "plausible": True, "expected_type": "compound"} for value in payload["compound"])
    cases.extend({"query": value, "plausible": False, "expected_type": None} for value in payload["nonsense"])
    return cases


async def evaluate(database: Path) -> dict:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    cases = corpus(payload)
    repository = HubRepository(database)
    repository.initialize()
    osm_snapshot = DATA.parent / "singapore-osm-pois.json"
    if osm_snapshot.exists():
        ingest_payload(repository, json.loads(osm_snapshot.read_text(encoding="utf-8")))
    resolver = NeedResolver(repository)
    counts: Counter[str] = Counter()
    latencies: list[float] = []
    wrong: list[str] = []
    for case in cases:
        started = time.perf_counter()
        needs = resolver.parse_open_needs(case["query"])
        latencies.append((time.perf_counter() - started) * 1000)
        accepted = bool(needs)
        counts["plausible_total" if case["plausible"] else "nonsense_total"] += 1
        counts["plausible_accepted"] += int(case["plausible"] and accepted)
        counts["false_nonsense_accepted"] += int(not case["plausible"] and accepted)
        if not case["plausible"] or not needs:
            continue
        if case["expected_type"] == "compound":
            counts["compound_complete"] += int(len(needs) == 2)
            resolved_parts = [
                await resolver.resolve(need.raw_text, allow_live=False, open_need=need)
                for need in needs[:2]
            ]
            resolved_count = sum(bool(item.places) for item in resolved_parts)
            counts["compound_partial"] += int(len(needs) == 2 and resolved_count == 1)
            counts["compound_resolved"] += int(len(needs) == 2 and resolved_count == 2)
            continue
        counts["resolution_eligible"] += 1
        result = await resolver.resolve(needs[0].raw_text, allow_live=False, open_need=needs[0])
        counts["resolved"] += int(bool(result.places))
        counts["unresolved"] += int(not result.places)
        expected = case["expected_type"]
        if expected:
            counts["typed_total"] += 1
            compatible = {
                "brand": {"brand", "specific_business"},
                "service": {"service", "place_type"},
            }.get(expected, {expected})
            if result.semantic_type.value not in compatible:
                wrong.append(case["query"])
    ordered = sorted(latencies)
    plausible = counts["plausible_total"]
    resolution_eligible = counts["resolution_eligible"]
    compounds = sum(1 for case in cases if case["expected_type"] == "compound")
    resolver_metrics = resolver.metrics_snapshot()
    return {
        "corpus_size": len(cases),
        "plausible_need_acceptance_rate": counts["plausible_accepted"] / plausible if plausible else 0,
        "false_nonsense_acceptance_rate": counts["false_nonsense_accepted"] / counts["nonsense_total"] if counts["nonsense_total"] else 0,
        "local_resolution_rate": counts["resolved"] / resolution_eligible if resolution_eligible else 0,
        "zero_result_rate": counts["unresolved"] / resolution_eligible if resolution_eligible else 0,
        "wrong_type_rate": len(wrong) / counts["typed_total"] if counts["typed_total"] else 0,
        "wrong_type_examples": wrong[:20],
        "wrong_place_rate": None,
        "wrong_place_rate_note": "Requires a human-labelled place-relevance set; unsupported candidates are filtered before routing.",
        "compound_complete_rate": counts["compound_complete"] / compounds if compounds else 0,
        "compound_partial_resolution_rate": counts["compound_partial"] / compounds if compounds else 0,
        "compound_full_resolution_rate": counts["compound_resolved"] / compounds if compounds else 0,
        "semantic_expansion_rate": resolver_metrics["semantic"] / resolver_metrics["total"] if resolver_metrics["total"] else 0,
        "llm_expansion_rate": resolver_metrics["llm_expansions"] / resolver_metrics["total"] if resolver_metrics["total"] else 0,
        "primary_live_fallback_rate": 0.0,
        "secondary_live_fallback_rate": 0.0,
        "web_fallback_rate": 0.0,
        "grounding_success_rate": 0.0,
        "mean_parser_latency_ms": statistics.fmean(latencies) if latencies else 0,
        "p95_parser_latency_ms": ordered[int((len(ordered) - 1) * 0.95)] if ordered else 0,
        "provider_calls": resolver_metrics["provider_calls"],
        "routing_calls_after_discovery": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if args.database:
        result = asyncio.run(evaluate(args.database))
    else:
        with tempfile.TemporaryDirectory(prefix="along-v074-", ignore_cleanup_errors=True) as directory:
            result = asyncio.run(evaluate(Path(directory) / "evaluation.db"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
