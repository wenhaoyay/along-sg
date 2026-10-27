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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ops import OpsSettings  # noqa: E402

CASES = ROOT / "data" / "phrasing-evaluation.json"
SINGAPORE = ZoneInfo("Asia/Singapore")


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
    errands = intent.get("required_errands", []) + intent.get("optional_errands", [])
    exact = case.get("exact_brand")
    if exact and exact not in {errand.get("exact_brand") for errand in errands}:
        return f"exact brand lost (expected {exact})"
    excluded = case.get("excluded_brand")
    if excluded:
        if not any(excluded in errand.get("excluded_brands", []) for errand in errands):
            return f"{excluded} not excluded"
        if excluded in preferred_brands(intent):
            return f"{excluded} excluded but also asked for"
    optional = case.get("optional")
    if optional and sorted(optional) != sorted(item["category"] for item in intent.get("optional_errands", [])):
        return f"optional {[item['category'] for item in intent.get('optional_errands', [])]}, expected {optional}"
    modifier = case.get("modifier")
    if modifier and not any(modifier in errand.get("modifiers", []) for errand in errands):
        return f"modifier {modifier} lost"
    preferences = intent["preferences"]
    arrival = case.get("arrival_time")
    if arrival:
        value = preferences.get("arrival_by")
        local = datetime.fromisoformat(value).astimezone(SINGAPORE).strftime("%H:%M") if value else None
        if local != arrival:
            return f"arrival_by {value}, expected {arrival} Singapore time"
    if "max_detour" in case and preferences.get("max_detour_minutes") != case["max_detour"]:
        return f"max detour {preferences.get('max_detour_minutes')}, expected {case['max_detour']}"
    if "detour_hard" in case and preferences.get("max_detour_is_hard") != case["detour_hard"]:
        return f"detour hard={preferences.get('max_detour_is_hard')}, expected {case['detour_hard']}"
    missing = [
        term for term in case.get("not_understood", [])
        if not any(term in reported for reported in body.get("unresolved_terms", []))
    ]
    if missing:
        return f"dropped without saying so: {missing}"
    if case.get("spelling") and not body.get("spelling_corrections"):
        return "spelling correction not reported"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-pass", type=float, default=0.0, help="exit 1 below this pass rate")
    args = parser.parse_args()
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    # One client sends every phrasing in a burst; the public rate limit is not what is being measured.
    app = create_app(
        Settings(onemap_mock=True, llm_intent_enabled=False, discovery_live_enabled=False),
        OpsSettings(rate_limit_enabled=False),
    )
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
