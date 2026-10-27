from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.poi_ingestion import (  # noqa: E402
    OSM_CAPTURE_FILE,
    catalogue_files,
    download_osm_payload,
    file_fingerprint,
    ingest_payload,
    load_catalogue,
    load_payload,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Singapore OpenStreetMap errand POIs")
    parser.add_argument("--input", type=Path, help="Use an existing Overpass JSON export")
    parser.add_argument(
        "--save-raw", type=Path,
        default=BACKEND_ROOT / "data" / "singapore-osm-pois.json",
        help="Where to save a newly downloaded attributed export",
    )
    parser.add_argument("--database", type=Path, help="SQLite database path")
    parser.add_argument(
        "--no-supplements", action="store_true",
        help="Ingest the capture alone, without the post offices and HSA pharmacies beside it",
    )
    args = parser.parse_args()

    fingerprint = None
    if args.input and args.input.name == OSM_CAPTURE_FILE and not args.no_supplements:
        # The bundled capture: merge the supplementary files kept beside it,
        # exactly as a deploy does, so both record the same fingerprint.
        payload = load_catalogue(args.input.parent)
        fingerprint = file_fingerprint(*catalogue_files(args.input.parent))
    elif args.input:
        payload = load_payload(args.input)
        fingerprint = file_fingerprint(args.input)
    else:
        payload = await download_osm_payload()
        args.save_raw.parent.mkdir(parents=True, exist_ok=True)
        args.save_raw.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    repository = HubRepository(args.database or Settings.from_env().database_path)
    repository.initialize()
    report = ingest_payload(repository, payload, fingerprint=fingerprint)
    print(json.dumps({"ingestion": asdict(report), "database": repository.stats()}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
