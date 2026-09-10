"""Ingest LTA's static bus network: stops, and the services calling at them.

    python scripts/ingest_bus_network.py                 # needs LTA_ACCOUNT_KEY
    python scripts/ingest_bus_network.py --input cap.json # replay a saved capture
    python scripts/ingest_bus_network.py --capture cap.json

Free: register at https://datamall.lta.gov.sg/ for an AccountKey. Ten million
calls a day, and the Singapore Open Data Licence permits storing the data and
serving it onward, which is why this can be a local table at all.

The static endpoints return a page at a time and are paged with `$skip`. The
page size is not promised in the guide, so this asks for pages until one comes
back shorter than the last full one rather than assuming 500.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.bus_network import transform_bus_routes, transform_bus_stops  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.domain import SINGAPORE_TZ  # noqa: E402
from app.providers.datamall import DATAMALL_BASE_URL  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("ingest_bus_network")

# Generous, because a truncated capture is refused rather than written and the
# cost of one wasted page is a retry.
MAX_PAGES = 200


async def fetch_all(client: httpx.AsyncClient, path: str, key: str) -> list[dict]:
    """Every record from a paged static dataset.

    Stops when a page is empty or repeats what the previous one held: a server
    that ignores `$skip` would otherwise loop forever handing back page one.
    """
    records: list[dict] = []
    seen_pages: set[str] = set()
    for page in range(MAX_PAGES):
        response = await client.get(
            f"{DATAMALL_BASE_URL}{path}",
            params={"$skip": page * 500},
            headers={"AccountKey": key, "accept": "application/json"},
        )
        response.raise_for_status()
        batch = response.json().get("value") or []
        if not batch:
            break
        fingerprint = json.dumps(batch[0], sort_keys=True)
        if fingerprint in seen_pages:
            logger.warning("%s repeated a page at skip=%s; stopping", path, page * 500)
            break
        seen_pages.add(fingerprint)
        records.extend(batch)
        logger.info("%s page %s -> %s records (%s total)", path, page, len(batch), len(records))
    return records


async def capture(key: str) -> dict[str, list[dict]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        stops = await fetch_all(client, "/BusStops", key)
        routes = await fetch_all(client, "/BusRoutes", key)
    return {"BusStops": stops, "BusRoutes": routes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="replay a saved capture instead of fetching")
    parser.add_argument("--capture", type=Path, help="write the raw capture here as well")
    parser.add_argument("--database", type=Path, default=None)
    arguments = parser.parse_args()

    settings = Settings.from_env()
    database = arguments.database or settings.database_path

    if arguments.input:
        payload = json.loads(arguments.input.read_text(encoding="utf-8"))
    else:
        key = settings.lta_account_key or os.getenv("LTA_ACCOUNT_KEY") or ""
        if not key:
            logger.error(
                "No LTA_ACCOUNT_KEY. Register free at https://datamall.lta.gov.sg/ "
                "and set it in backend/.env, or pass --input with a saved capture."
            )
            return 2
        payload = asyncio.run(capture(key))
        if arguments.capture:
            arguments.capture.write_text(json.dumps(payload), encoding="utf-8")
            logger.info("capture written to %s", arguments.capture)

    stops = transform_bus_stops(payload.get("BusStops") or [])
    routes = transform_bus_routes(payload.get("BusRoutes") or [])
    logger.info(
        "transformed %s stops and %s route rows (from %s and %s raw)",
        len(stops), len(routes),
        len(payload.get("BusStops") or []), len(payload.get("BusRoutes") or []),
    )

    repository = HubRepository(database)
    repository.initialize()
    try:
        written = repository.replace_bus_network(
            stops, routes, datetime.now(SINGAPORE_TZ).isoformat()
        )
    except ValueError as error:
        # Deliberately fatal. Half a bus network is worse than none: the app
        # would report services as not running because their rows are missing.
        logger.error("%s", error)
        return 1
    logger.info("wrote %s stops and %s route rows", *written)
    services = len({row["service_no"] for row in routes})
    logger.info("%s distinct services now known", services)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
