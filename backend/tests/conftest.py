from __future__ import annotations

from pathlib import Path

import pytest

from app.db import HubRepository


@pytest.fixture
def repository(tmp_path: Path) -> HubRepository:
    repo = HubRepository(tmp_path / "test.db")
    repo.initialize()
    return repo
