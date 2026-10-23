"""How much the routing budget costs: the pick against a search with no pruning.

The planner routes a handful of candidates, chosen by a cheap network-distance
proxy, because a live router is slow and rationed. That pruning is the one
step that can silently lose the right answer (it lost Waterway Point once,
and the Koi Express + JEM pair until 0.11). This tool measures it.

Each journey is planned twice, in process, on the full catalogue with the
offline rail network:

- as deployed: the normal candidate limits and routing budget;
- unpruned: the same scoring with the limits opened wide (hundreds of
  candidates, a wide corridor, a budget nothing reaches), so every reasonable
  place is actually routed.

Same parser, same scoring, same preferences: the only difference is how many
places get routed. It reports how often the deployed pick is the unpruned
pick, and how much extra travel the misses cost. Build the catalogue first:

    cd backend
    .venv\\Scripts\\python.exe scripts\\ingest_osm_pois.py --input data\\singapore-osm-pois.json
    .venv\\Scripts\\python.exe tools\\compare_exhaustive.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ops import OpsSettings  # noqa: E402

JOURNEYS = [
    ("Punggol MRT", "Orchard MRT", "panadol and some groceries, prefer FairPrice"),
    ("Jurong East MRT", "Raffles Place MRT", "KFC and bubble tea"),
    ("Tampines MRT", "HarbourFront MRT", "coffee and a birthday cake"),
    ("Woodlands MRT", "Tanjong Pagar MRT", "buy milk"),
    ("Tampines MRT", "Orchard MRT", "groceries, and coffee if convenient"),
    ("Jurong East MRT", "Changi Airport", "KFC and bubble tea"),
    ("Bugis MRT", "City Hall MRT", "haircut and post a parcel"),
    ("Bishan MRT", "HarbourFront MRT", "bubble tea"),
    ("Pasir Ris MRT", "Bukit Panjang MRT", "pharmacy"),
    ("Serangoon MRT", "Outram Park MRT", "groceries"),
    ("Ang Mo Kio MRT", "Bugis MRT", "pharmacy and an ATM"),
    ("Clementi MRT", "Paya Lebar MRT", "coffee"),
    ("Yishun MRT", "Dhoby Ghaut MRT", "groceries and bubble tea"),
    ("Boon Lay MRT", "Bishan MRT", "McDonald's"),
    ("Sengkang MRT", "Novena MRT", "pharmacy"),
    ("Bedok MRT", "Jurong East MRT", "groceries and pharmacy"),
    ("Toa Payoh MRT", "Marina Bay MRT", "bakery"),
    ("Hougang MRT", "Somerset MRT", "post office"),
    ("Kallang MRT", "Woodlands MRT", "convenience store"),
    ("Buona Vista MRT", "Tampines MRT", "coffee and groceries"),
]

UNPRUNED = dict(
    max_candidates=200,
    routing_soft_budget=4000,
    routing_hard_budget=8000,
    candidate_corridor_km=4.0,
    candidate_endpoint_radius_km=3.0,
    candidate_max_hubs_per_category=60,
    max_straight_line_detour_km=30.0,
)


def plan(client: TestClient, origin: str, destination: str, text: str) -> dict | None:
    parsed = client.post("/api/intent/parse", json={"text": text}).json()
    if parsed.get("status") != "resolved" or not parsed.get("intent"):
        return None
    response = client.post(
        "/api/optimize-intent",
        json={
            "origin": {"query": origin},
            "destination": {"query": destination},
            "intent": parsed["intent"],
            "departure": "2026-10-26T10:00:00+08:00",
        },
    )
    if response.status_code != 200:
        return None
    best = response.json()["recommendations"].get("best_overall")
    if best is None:
        return None
    return {
        "stops": " then ".join(stop["display_name"] for stop in best["stops"]),
        "travel": best["incremental_travel_minutes"],
        "score": best["inconvenience_score"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="Also write the results here")
    args = parser.parse_args()
    logging.disable(logging.WARNING)

    base = Settings.from_env()
    common = dict(onemap_mock=True, llm_intent_enabled=False, discovery_live_enabled=False)
    deployed = replace(base, **common)
    unpruned = replace(base, **common, **UNPRUNED)
    ops = OpsSettings(rate_limit_enabled=False)

    rows = []
    with TestClient(create_app(deployed, ops)) as fast, TestClient(create_app(unpruned, ops)) as wide:
        for origin, destination, text in JOURNEYS:
            pick = plan(fast, origin, destination, text)
            best = plan(wide, origin, destination, text)
            rows.append({"journey": f"{origin} → {destination}", "request": text, "deployed": pick, "unpruned": best})

    compared = [row for row in rows if row["deployed"] and row["unpruned"]]
    same = [row for row in compared if row["deployed"]["stops"] == row["unpruned"]["stops"]]
    gaps = [
        max(0.0, row["deployed"]["travel"] - row["unpruned"]["travel"])
        for row in compared
        if row not in same
    ]
    for row in rows:
        pick, best = row["deployed"], row["unpruned"]
        if not pick or not best:
            print(f"  skipped  {row['journey']} | {row['request']}")
            continue
        mark = "same" if pick["stops"] == best["stops"] else f"+{pick['travel'] - best['travel']:.1f} min"
        print(f"  {mark:>9}  {row['journey']} | {row['request']}")
        if pick["stops"] != best["stops"]:
            print(f"             deployed {pick['stops']} ({pick['travel']:.1f}) vs unpruned {best['stops']} ({best['travel']:.1f})")
    print(
        f"\nSame pick as the unpruned search on {len(same)} of {len(compared)} journeys."
        + (f" Misses cost at most {max(gaps):.1f} min of extra travel." if gaps else "")
    )
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
