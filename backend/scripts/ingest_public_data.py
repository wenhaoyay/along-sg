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
from app.public_data import (  # noqa: E402
    DATASETS,
    DataGovSgClient,
    PublicGeoStore,
    ingest_parsed_dataset,
    parse_dataset,
)


def _raw_path(directory: Path, key: str, file_format: str) -> Path:
    suffix = ".csv" if file_format == "csv" else ".geojson"
    return directory / f"{key}{suffix}"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest official Singapore public datasets into Along"
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=tuple(DATASETS),
        default=list(DATASETS),
        help="Datasets to ingest. Defaults to every configured public dataset.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Read dataset snapshots from this directory instead of downloading.",
    )
    parser.add_argument(
        "--save-raw-dir",
        type=Path,
        help="Optionally save newly downloaded snapshots for inspection.",
    )
    parser.add_argument("--database", type=Path, help="SQLite database path")
    args = parser.parse_args()

    database_path = args.database or Settings.from_env().database_path
    repository = HubRepository(database_path)
    repository.initialize()
    geo_store = PublicGeoStore(database_path)
    geo_store.initialize()
    client = DataGovSgClient()

    requested = list(dict.fromkeys(args.datasets))
    if "mrt_exits" in requested:
        requested.remove("mrt_exits")
        requested.insert(0, "mrt_exits")

    reports = []
    for key in requested:
        spec = DATASETS[key]
        if args.input_dir:
            path = _raw_path(args.input_dir, key, spec.file_format)
            raw = path.read_bytes()
        else:
            raw = await client.download(spec)
            if args.save_raw_dir:
                args.save_raw_dir.mkdir(parents=True, exist_ok=True)
                _raw_path(args.save_raw_dir, key, spec.file_format).write_bytes(raw)

        parsed = parse_dataset(spec, raw)
        reports.append(asdict(ingest_parsed_dataset(repository, geo_store, parsed)))

    print(
        json.dumps(
            {
                "datasets": reports,
                "catalog": repository.stats(),
                "public_geo_layers": geo_store.counts_by_layer(),
                "database": str(database_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
