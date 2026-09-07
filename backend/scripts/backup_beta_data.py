"""Create consistent SQLite backups without copying an open database file."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as target_db:
        source_db.backup(target_db)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("/data"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for name in ("errands.db", "analytics.db"):
        backup(args.data_dir / name, args.output_dir / f"{Path(name).stem}-{stamp}.db")
    print(f"Created consistent SQLite backups in {args.output_dir}")


if __name__ == "__main__":
    main()
