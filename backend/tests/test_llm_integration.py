from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.db import HubRepository
from app.intent_models import IntentStatus
from app.providers.llm import OpenAIIntentProvider
from app.services.intent_parser import IntentParserService


pytestmark = pytest.mark.llm_integration


def _enabled() -> bool:
    return (
        os.getenv("RUN_LLM_INTEGRATION", "").lower() == "true"
        and bool(os.getenv("OPENAI_API_KEY"))
    )


@pytest.mark.skipif(not _enabled(), reason="set RUN_LLM_INTEGRATION=true explicitly")
@pytest.mark.asyncio
async def test_live_llm_structured_intent_is_canonical(tmp_path: Path):
    provider = OpenAIIntentProvider(
        os.environ["OPENAI_API_KEY"],
        os.getenv("OPENAI_INTENT_MODEL", "gpt-4.1-mini"),
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    repo = HubRepository(tmp_path / "llm.db")
    repo.initialize()
    try:
        response = await IntentParserService(repo, provider).parse(
            "I want something caffeinated if it is easy, but medicine is mandatory"
        )
    finally:
        await provider.close()
    assert response.status == IntentStatus.RESOLVED
    assert [item.category for item in response.intent.required_errands] == ["pharmacy"]
    assert [item.category for item in response.intent.optional_errands] == ["coffee"]
