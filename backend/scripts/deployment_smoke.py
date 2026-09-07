"""Smoke-test the production shape: one FastAPI process serving the static UI and API."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-dir", type=Path, required=True)
    args = parser.parse_args()
    frontend = args.frontend_dir.resolve()
    if not (frontend / "index.html").is_file():
        raise SystemExit(f"Missing exported frontend at {frontend}")

    with tempfile.TemporaryDirectory(prefix="along-the-way-smoke-") as temp:
        storage = Path(temp)
        settings = Settings(
            onemap_mock=True,
            database_path=storage / "errands.db",
            analytics_database_path=storage / "analytics.db",
            serve_frontend_dir=frontend,
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").json()["status"] == "ok"
            assert "What do you need on the way?" in client.get("/").text
            assert client.get("/privacy").status_code == 200
            journey = client.post(
                "/api/journey",
                json={
                    "origin": {"query": "Punggol MRT"},
                    "destination": {"query": "Orchard MRT"},
                },
            )
            journey.raise_for_status()
            assert journey.json()["route"]["provider"] == "onemap-mock"
    print("Deployment smoke passed: static UI, privacy page, health and mock API.")


if __name__ == "__main__":
    main()
