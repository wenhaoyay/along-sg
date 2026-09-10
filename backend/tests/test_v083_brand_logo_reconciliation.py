from __future__ import annotations

import httpx
import pytest

from app.db import HubRepository
from scripts.ingest_brand_logos import fetch_entity, reconcile_capture


def _logo(qid: str, url: str = "old") -> dict[str, str]:
    return {
        "wikidata_id": qid,
        "brand_label": qid,
        "file_name": "old.svg",
        "url": url,
    }


def test_malformed_success_body_preserves_existing_logo(tmp_path) -> None:
    repository = HubRepository(tmp_path / "malformed.db")
    repository.initialize()
    repository.upsert_brand_logos([_logo("Q1")])

    written, deleted, usable = reconcile_capture(repository, {"Q1": {}}, "now")

    assert (written, deleted, usable) == (0, 0, 0)
    assert repository.brand_logo_urls() == {"Q1": "old"}


def test_malformed_entity_claims_preserve_existing_logo(tmp_path) -> None:
    repository = HubRepository(tmp_path / "claims.db")
    repository.initialize()
    repository.upsert_brand_logos([_logo("Q1")])
    payload = {"entities": {"Q1": {"claims": "broken"}}}

    written, deleted, usable = reconcile_capture(repository, {"Q1": payload}, "now")

    assert (written, deleted, usable) == (0, 0, 0)
    assert repository.brand_logo_urls() == {"Q1": "old"}


def test_ambiguous_entity_body_preserves_existing_logo(tmp_path) -> None:
    repository = HubRepository(tmp_path / "ambiguous.db")
    repository.initialize()
    repository.upsert_brand_logos([_logo("Q1")])
    payload = {"entities": {"Q2": {}, "Q3": {}}}

    written, deleted, usable = reconcile_capture(repository, {"Q1": payload}, "now")

    assert (written, deleted, usable) == (0, 0, 0)
    assert repository.brand_logo_urls() == {"Q1": "old"}


@pytest.mark.asyncio
async def test_network_failure_is_not_returned_as_a_successful_payload() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        assert await fetch_entity(client, "Q1") is None
