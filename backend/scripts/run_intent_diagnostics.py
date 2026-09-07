"""Run safe offline consumer-intent recommendation diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


CASES = (
    ("A", "Boon Lay MRT", "Fajar LRT", "fried chicken"),
    ("B", "Boon Lay MRT", "Fajar LRT", "fried chicken and bubble tea"),
    ("C", "Punggol MRT", "Orchard MRT", "groceries and pharmacy"),
    ("D", "NUS", "Bukit Panjang MRT", "KFC, but other fried chicken is okay"),
    ("E", "NUS", "Bukit Panjang MRT", "must be KFC"),
    ("F", "Jurong East MRT", "Tampines MRT", "bubble tea under 10 minutes max"),
    ("G", "Punggol MRT", "Orchard MRT", "coffee if convenient"),
)


def location_input(label: str) -> dict:
    if label == "NUS":
        return {"query": "National University of Singapore"}
    if label == "Bukit Panjang MRT":
        return {"coordinate": {"latitude": 1.3774, "longitude": 103.7630}}
    return {"query": label}


def main() -> None:
    app = create_app(Settings(onemap_mock=True))
    results = []
    with TestClient(app) as client:
        for case_id, origin, destination, prompt in CASES:
            parsed = client.post("/api/intent/parse", json={"text": prompt})
            parsed.raise_for_status()
            preview = parsed.json()
            item = {
                "case": case_id,
                "origin": origin,
                "destination": destination,
                "query": prompt,
                "parse_status": preview["status"],
                "parser_latency_ms": preview["diagnostics"]["parser_latency_ms"],
                "intent": preview.get("intent"),
            }
            if preview["status"] == "resolved":
                optimized = client.post(
                    "/api/optimize-intent",
                    json={
                        "origin": location_input(origin),
                        "destination": location_input(destination),
                        "intent": preview["intent"],
                    },
                )
                optimized.raise_for_status()
                body = optimized.json()
                best = body["recommendations"].get("best_overall")
                item["recommendation"] = (
                    {
                        "classification": best["match_classification"],
                        "quality_label": best["quality_label"],
                        "hard_requirements_met": best["hard_constraints_satisfied"],
                        "stops": [
                            {
                                "name": stop["name"],
                                "context": stop["location_context"],
                            }
                            for stop in best["stops"]
                        ],
                        "incremental_detour_minutes": best[
                            "incremental_detour_minutes"
                        ],
                    }
                    if best
                    else None
                )
                item["routing_call_count"] = body["diagnostics"][
                    "routing_call_count"
                ]
                item["optimization_latency_ms"] = body["diagnostics"][
                    "optimization_latency_ms"
                ]
                item["outcome"] = body["diagnostics"]["outcome"]
                item["alternatives"] = [
                    {
                        "quality_label": value["quality_label"],
                        "classification": value["match_classification"],
                        "detour_minutes": value["incremental_detour_minutes"],
                    }
                    for key, value in body["recommendations"].items()
                    if key != "best_overall"
                ]
            results.append(item)
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
