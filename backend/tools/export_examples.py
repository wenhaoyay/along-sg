"""Save the homepage examples' real API answers as static JSON.

A free Render instance sleeps when idle and takes about a minute to wake, so
the homepage can show its examples from files instead of waiting on the API.
This runs each example exactly as the page does - POST /api/intent/parse with
the example's request and endpoints, then POST /api/optimize-intent with the
parsed intent - in process, in the demo's offline configuration (mock
routing, no live discovery, no LLM, diagnostics hidden), and writes both
responses unchanged to frontend/public/examples/<id>.json:

    {"id": ..., "generated_at": ..., "request": {...},
     "parse": <parse response>, "optimize": <optimize-intent response>}

The examples are read from frontend/app/examples.ts, so the two never drift.
Times in the answers (departure, arrivals, open-now) are those of the moment
the file was generated. Build the full catalogue first:

    cd backend
    .venv\\Scripts\\python.exe scripts\\ingest_osm_pois.py --input data\\singapore-osm-pois.json
    .venv\\Scripts\\python.exe tools\\export_examples.py [--out DIR] [--departure ISO]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.domain import SINGAPORE_TZ  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ops import OpsSettings  # noqa: E402

FRONTEND = ROOT.parent / "frontend"
EXAMPLES_SOURCE = FRONTEND / "app" / "examples.ts"
DEFAULT_OUT = FRONTEND / "public" / "examples"

_STATION = r'station\(\s*"(?P<{0}_label>[^"]+)",\s*(?P<{0}_lat>-?[\d.]+),\s*(?P<{0}_lon>-?[\d.]+),'
_EXAMPLE = re.compile(
    r'id:\s*"(?P<id>[a-z0-9-]+)",\s*'
    r"origin:\s*" + _STATION.format("origin") + r".*?"
    r"destination:\s*" + _STATION.format("destination") + r".*?"
    r'need:\s*"(?P<need>[^"]+)"',
    re.DOTALL,
)


def read_examples(source: Path = EXAMPLES_SOURCE) -> list[dict]:
    examples = []
    for match in _EXAMPLE.finditer(source.read_text(encoding="utf-8")):
        examples.append({
            "id": match["id"],
            "need": match["need"],
            **{
                endpoint: {
                    "label": match[f"{endpoint}_label"],
                    "coordinate": {
                        "latitude": float(match[f"{endpoint}_lat"]),
                        "longitude": float(match[f"{endpoint}_lon"]),
                    },
                }
                for endpoint in ("origin", "destination")
            },
        })
    if not examples:
        raise SystemExit(f"No examples found in {source}; has its shape changed?")
    return examples


def demo_settings() -> Settings:
    """What render.yaml deploys: offline, nothing live, diagnostics private."""
    return Settings(
        onemap_mock=True,
        datamall_mock=True,
        llm_intent_enabled=False,
        discovery_live_enabled=False,
        discovery_web_enabled=False,
        discovery_semantic_llm_enabled=False,
        expose_diagnostics=False,
    )


def run_example(client: TestClient, example: dict, departure: str | None) -> dict:
    endpoints = {"origin": example["origin"], "destination": example["destination"]}
    parsed = client.post("/api/intent/parse", json={"text": example["need"], **endpoints})
    if parsed.status_code != 200:
        raise SystemExit(f"{example['id']}: parse answered {parsed.status_code}: {parsed.text}")
    parse = parsed.json()
    if parse.get("status") != "resolved" or not parse.get("intent") or parse.get("journey_conflicts"):
        raise SystemExit(
            f"{example['id']}: the page would ask a question here, not plan: "
            f"{parse.get('clarification_question')!r}"
        )
    optimized = client.post("/api/optimize-intent", json={
        "origin": {"coordinate": example["origin"]["coordinate"]},
        "destination": {"coordinate": example["destination"]["coordinate"]},
        "departure": departure,
        "intent": parse["intent"],
        "confirmed_discovery_places": [],
    })
    if optimized.status_code != 200:
        raise SystemExit(
            f"{example['id']}: optimize-intent answered {optimized.status_code}: {optimized.text}"
        )
    return {
        "id": example["id"],
        "generated_at": datetime.now(SINGAPORE_TZ).isoformat(timespec="seconds"),
        "request": {"need": example["need"], **endpoints, "departure": departure},
        "parse": parse,
        "optimize": optimized.json(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Directory for <id>.json")
    parser.add_argument(
        "--departure",
        help="Future departure in ISO 8601 (Singapore time if no offset); default: now",
    )
    args = parser.parse_args()

    settings = demo_settings()
    if HubRepository(settings.database_path).count_outlets(active_only=False) <= 30:
        raise SystemExit(
            f"{settings.database_path} holds only the seed catalogue; "
            "run scripts/ingest_osm_pois.py first."
        )
    args.out.mkdir(parents=True, exist_ok=True)
    app = create_app(settings, OpsSettings(rate_limit_enabled=False, analytics_enabled=False))
    with TestClient(app) as client:
        for example in read_examples():
            result = run_example(client, example, args.departure)
            target = args.out / f"{example['id']}.json"
            target.write_text(
                json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            plans = sum(
                1 for item in result["optimize"]["recommendations"].values() if item.get("offered", True)
            )
            print(f"{target.relative_to(ROOT.parent) if target.is_relative_to(ROOT.parent) else target}: "
                  f"{result['optimize']['outcome']}, {plans} plan(s), {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
