"""Initialize a persistent beta SQLite volume from the bundled OSM capture once."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings
from app.db import HubRepository
from app.poi_ingestion import ingest_payload


def main() -> None:
    settings = Settings.from_env()
    repository = HubRepository(settings.database_path)
    repository.initialize()
    if repository.count_outlets(active_only=False) <= 30:
        capture = BACKEND_ROOT / "data" / "singapore-osm-pois.json"
        ingest_payload(repository, json.loads(capture.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
