"""Fetch brand logos from Wikidata for every brand the catalogue knows.

    python scripts/ingest_brand_logos.py                  # fetch and store
    python scripts/ingest_brand_logos.py --input cap.json # replay a capture
    python scripts/ingest_brand_logos.py --capture cap.json

Free and keyless. Wikidata and Wikimedia Commons carry no account or per-call
cost, which is the whole reason logos are the answer to idea 3 and photographs
are not - the providers that hold photographs of Singapore shopfronts either
charge, forbid storing what they return, or both.

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
    resolve_entity_payload,
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
        # Treat an HTTP failure as an unsuccessful fetch. A stale OSM tag can
        # point at a deleted entity, but a transient/proxy 404 is still not a
        # trustworthy signal for deleting the last known logo.
        logger.warning("%s: HTTP 404", qid)
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
    """Return only QIDs whose EntityData request completed successfully.

    Missing entries are fetch failures and must preserve any previously stored
    logo. A successful payload that contains no usable logo is different: that
    QID is present here and reconciliation may remove its stale row.
    """
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


def reconcile_capture(
    repository: HubRepository,
    captured: dict[str, dict],
    fetched_at: str,
) -> tuple[int, int, int]:
    """Reconcile only successfully fetched and safely parsed QIDs.

    Valid logos are upserted. A valid entity that no longer exposes a usable
    logo removes the old row. Request failures are absent from ``captured`` and
    malformed or ambiguous payloads cannot be resolved, so both cases preserve
    the prior database value. This keeps partial refreshes safe.
    """
    logos = []
    no_logo_qids = []
    for qid, payload in captured.items():
        entity = resolve_entity_payload(payload, qid)
        if entity is None or not isinstance(entity.get("claims"), dict):
            logger.warning(
                "%s: EntityData payload could not be parsed safely; preserving prior logo",
                qid,
            )
            continue
        row = parse_entity_payload(payload, qid)
        if row is None:
            no_logo_qids.append(qid)
        else:
            logos.append(row)

    written = repository.upsert_brand_logos(logos, fetched_at)
    deleted = 0
    if no_logo_qids:
        placeholders = ",".join("?" for _ in no_logo_qids)
        # HubRepository owns the SQLite path and connection policy. This stays
        # at the ingestion boundary rather than changing generic upsert
        # semantics: deletion is valid only for entities resolved successfully
        # in this particular refresh.
        with repository._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM brand_logos WHERE wikidata_id IN ({placeholders})",
                no_logo_qids,
            )
            deleted = max(0, int(cursor.rowcount))
    return written, deleted, len(logos)


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

    fetched_at = datetime.now(SINGAPORE_TZ).isoformat()
    written, deleted, usable = reconcile_capture(repository, captured, fetched_at)
    # Most brands genuinely have no logo claim, so this is a coverage figure
    # rather than a failure count.
    logger.info(
        "%s brands answered, %s carried a usable logo, %s stored, %s stale removed "
        "(%s held in total)",
        len(captured), usable, written, deleted, repository.brand_logo_count(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
