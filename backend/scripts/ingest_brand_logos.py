"""Fetch brand logos from Wikidata for every brand the catalogue knows.

    python scripts/ingest_brand_logos.py                  # fetch and store
    python scripts/ingest_brand_logos.py --input cap.json # replay a capture
    python scripts/ingest_brand_logos.py --capture cap.json

Free and keyless. Wikidata and Wikimedia Commons carry no account, no quota and
no per-call cost, which is the whole reason logos are the answer to idea 3 and
photographs are not - the providers that hold photographs of Singapore shopfronts
either charge, forbid storing what they return, or both.

One request per distinct brand, not per outlet: 601 brands cover 4,077 outlets.
The Commons URL is derived from the file name rather than looked up, so there is
no second request per logo either.

Wikimedia answers 403 to a terse User-Agent, so `brand_logos.USER_AGENT` carries
a contact URL as their policy requires. Requests are also spaced, because
hammering a donated service to save ninety seconds would be rude.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.brand_logos import (  # noqa: E402
    USER_AGENT,
    WIKIDATA_ENTITY_URL,
    parse_entity_payload,
)
from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.domain import SINGAPORE_TZ  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("ingest_brand_logos")

# Polite spacing between requests to a donated service.
REQUEST_INTERVAL_SECONDS = 0.12


async def fetch_entity(client: httpx.AsyncClient, qid: str) -> dict | None:
    try:
        response = await client.get(WIKIDATA_ENTITY_URL.format(qid=qid))
    except httpx.HTTPError as error:
        logger.warning("%s: request failed (%s)", qid, type(error).__name__)
        return None
    if response.status_code == 404:
        # A deleted id. Ordinary: OSM tags outlive Wikidata items.
        return None
    if response.status_code != 200:
        logger.warning("%s: HTTP %s", qid, response.status_code)
        return None
    try:
        return response.json()
    except ValueError:
        logger.warning("%s: non-JSON body", qid)
        return None


async def fetch_all(qids: list[str]) -> dict[str, dict]:
    captured: dict[str, dict] = {}
    async with httpx.AsyncClient(
        timeout=20.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        for index, qid in enumerate(qids, start=1):
            payload = await fetch_entity(client, qid)
            if payload is not None:
                captured[qid] = payload
            if index % 50 == 0:
                logger.info("fetched %s of %s", index, len(qids))
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
    return captured


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="replay a saved capture instead of fetching")
    parser.add_argument("--capture", type=Path, help="write the raw capture here as well")
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="only the N commonest brands")
    arguments = parser.parse_args()

    settings = Settings.from_env()
    repository = HubRepository(arguments.database or settings.database_path)
    repository.initialize()

    if arguments.input:
        captured = json.loads(arguments.input.read_text(encoding="utf-8"))
    else:
        qids = repository.brand_wikidata_ids()
        if arguments.limit:
            qids = qids[: arguments.limit]
        if not qids:
            logger.error(
                "No outlet carries a brand:wikidata tag. Run "
                "scripts/ingest_osm_pois.py first."
            )
            return 2
        logger.info("%s distinct brands to look up", len(qids))
        captured = asyncio.run(fetch_all(qids))
        if arguments.capture:
            arguments.capture.write_text(json.dumps(captured), encoding="utf-8")
            logger.info("capture written to %s", arguments.capture)

    logos = [
        row for row in (
            parse_entity_payload(payload, qid) for qid, payload in captured.items()
        ) if row is not None
    ]
    written = repository.upsert_brand_logos(
        logos, datetime.now(SINGAPORE_TZ).isoformat()
    )
    # Most brands genuinely have no logo claim, so this is a coverage figure
    # rather than a failure count.
    logger.info(
        "%s brands answered, %s carried a usable logo, %s stored (%s held in total)",
        len(captured), len(logos), written, repository.brand_logo_count(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
