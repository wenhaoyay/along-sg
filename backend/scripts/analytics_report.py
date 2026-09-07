"""Print the aggregate private-beta report without exposing individual events."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analytics import AnalyticsRepository
from app.config import Settings


def main() -> None:
    settings = Settings.from_env()
    repository = AnalyticsRepository(
        settings.analytics_database_path, settings.analytics_retention_days
    )
    repository.initialize()
    print(repository.report().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
