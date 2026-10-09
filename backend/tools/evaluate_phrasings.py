"""Score the request parser on everyday phrasings.

Runs every case in data/phrasing-evaluation.json through /api/intent/parse,
in process, against the built catalog in mock mode (offline, no keys), and
prints a pass rate and each failure. A regression tool for the parser, not a
claim about every sentence a person might type.

    .venv\\Scripts\\python.exe tools\\evaluate_phrasings.py [--min-pass 0.9]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

CASES = ROOT / "data" / "phrasing-evaluation.json"


def found_categories(intent: dict) -> list[str]:
    categories: list[str] = []
    for errand in intent.get("required_errands", []) + intent.get("optional_errands", []):
        need = errand.get("open_need") or {}
        categories.append(errand.get("discovery_category") or need.get("category_hint") or errand["category"])
    return categories


def preferred_brands(intent: dict) -> set[str]:
    return {
        errand[key]
        for errand in intent.get("required_errands", []) + intent.get("optional_errands", [])
        for key in ("preferred_brand", "exact_brand")
        if errand.get(key)
    }


def check(case: dict, body: dict) -> str | None:
    intent = body.get("intent") if body.get("status") == "resolved" else None
    if case.get("reject"):
        return None if intent is None else f"accepted as an errand: {found_categories(intent)}"
    if intent is None:
        return f"{body.get('status')}: {body.get('clarification_question')}"
    found = found_categories(intent)
    if sorted(found) != sorted(case["expect"]):
        return f"found {found}, expected {case['expect']}"
    walking = case.get("walking")
    if walking and intent["preferences"]["walking_tolerance"] != walking:
        return f"walking {intent['preferences']['walking_tolerance']}, expected {walking}"
    brand = case.get("preferred_brand")
    if brand and brand not in preferred_brands(intent):
        return f"brand preference lost (expected {brand})"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-pass", type=float, default=0.0, help="exit 1 below this pass rate")
    args = parser.parse_args()
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    app = create_app(Settings(onemap_mock=True, llm_intent_enabled=False, discovery_live_enabled=False))
    failures: list[tuple[str, str, str]] = []
    with TestClient(app) as client:
        for case in cases:
            response = client.post("/api/intent/parse", json={"text": case["text"]})
            problem = check(case, response.json()) if response.status_code == 200 else f"HTTP {response.status_code}"
            if problem:
                failures.append((case.get("set", "tuned"), case["text"], problem))
    for name in dict.fromkeys(case.get("set", "tuned") for case in cases):
        total = sum(1 for case in cases if case.get("set", "tuned") == name)
        failed = sum(1 for item in failures if item[0] == name)
        print(f"{name:>9}: {total - failed}/{total} parsed as expected ({(total - failed) / total:.0%})")
    rate = (len(cases) - len(failures)) / len(cases)
    print(f"{'all':>9}: {len(cases) - len(failures)}/{len(cases)} ({rate:.0%})")
    for name, text, problem in failures:
        print(f"  FAIL [{name}] {text!r}: {problem}")
    return 1 if rate < args.min_pass else 0


if __name__ == "__main__":
    raise SystemExit(main())
