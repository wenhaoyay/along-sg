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
from app.poi_ingestion import download_osm_payload, ingest_payload, load_payload  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Singapore OpenStreetMap errand POIs")
    parser.add_argument("--input", type=Path, help="Use an existing Overpass JSON export")
    parser.add_argument(
        "--save-raw", type=Path,
        default=BACKEND_ROOT / "data" / "singapore-osm-pois.json",
        help="Where to save a newly downloaded attributed export",
    )
    parser.add_argument("--database", type=Path, help="SQLite database path")
    args = parser.parse_args()

    if args.input:
        payload = load_payload(args.input)
    else:
        payload = await download_osm_payload()
        args.save_raw.parent.mkdir(parents=True, exist_ok=True)
        args.save_raw.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    repository = HubRepository(args.database or Settings.from_env().database_path)
    repository.initialize()
    report = ingest_payload(repository, payload)
    print(json.dumps({"ingestion": asdict(report), "database": repository.stats()}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
