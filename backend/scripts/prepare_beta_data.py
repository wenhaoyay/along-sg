"""Bring a persistent beta SQLite volume up to the bundled catalogue capture.

Runs on every deploy. It used to ingest only into a database holding the
30-outlet seed, so once a volume had been filled, a newer capture shipped in
the image never reached it. The catalogue now records a fingerprint of the
capture files and the transform version (`catalog_meta`), and this script
re-ingests whenever the bundled files no longer match it.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db import HubRepository  # noqa: E402
from app.poi_ingestion import (  # noqa: E402
    catalogue_files,
    file_fingerprint,
    ingest_payload,
    load_catalogue,
)


def needs_ingest(repository: HubRepository, fingerprint: str) -> bool:
    if repository.count_outlets(active_only=False) <= 30:
        return True
    return repository.get_meta("catalogue_fingerprint") != fingerprint


def main(data_dir: Path | None = None) -> bool:
    """Returns whether it ingested, so a caller can log it."""
    settings = Settings.from_env()
    repository = HubRepository(settings.database_path)
    repository.initialize()
    files = catalogue_files(data_dir)
    fingerprint = file_fingerprint(*files)
    if not needs_ingest(repository, fingerprint):
        print("Catalogue is current; nothing to ingest.")
        return False
    report = ingest_payload(repository, load_catalogue(data_dir), fingerprint=fingerprint)
    print(
        f"Ingested capture {report.captured_at}: {report.imported_pois} outlets, "
        f"{report.imported_hubs} hubs."
    )
    return True


if __name__ == "__main__":
    main()
