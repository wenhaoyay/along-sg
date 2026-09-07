"""Explicitly gated, secret-free Tavily probe for V0.7.4 grounding diagnosis."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.providers.web_search import TavilyWebDiscoveryProvider  # noqa: E402


async def probe(queries: list[str], output: Path) -> None:
    settings = Settings.from_env()
    if not settings.tavily_api_key:
        raise SystemExit("TAVILY_API_KEY is not configured")
    provider = TavilyWebDiscoveryProvider(
        settings.tavily_api_key, settings.discovery_timeout_seconds,
    )
    results = []
    try:
        for query in queries:
            matches = await provider.search(query, 5)
            results.append({
                "query": query,
                "matches": [{
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                    "score": item.score,
                } for item in matches],
            })
    finally:
        await provider.close()
    payload = {
        "live_captured": True,
        "provider": "tavily",
        "credentials_recorded": False,
        "calls": provider.calls,
        "latency_ms": provider.latency_ms,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"calls": provider.calls, "latency_ms": provider.latency_ms}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("queries", nargs="+")
    args = parser.parse_args()
    if not args.run_live:
        raise SystemExit("Refusing live calls without --run-live")
    asyncio.run(probe(args.queries, args.output))


if __name__ == "__main__":
    main()
