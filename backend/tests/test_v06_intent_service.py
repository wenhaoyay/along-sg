from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from app.intent_models import IntentErrand, IntentStatus, IntentV1, ParseMethod
from app.providers.llm import LLMIntentResult, OpenAIIntentProvider
from app.services.intent_parser import IntentParserService


@dataclass
class FakeLLM:
    intent: IntentV1 | None = None
    error: Exception | None = None
    calls: int = 0

    async def parse_intent(self, text, categories, brands):
        self.calls += 1
        if self.error:
            raise self.error
        assert self.intent is not None
        return LLMIntentResult(
            self.intent, latency_ms=12.5, input_tokens=100, output_tokens=40,
            total_tokens=140,
        )


@pytest.mark.asyncio
async def test_easy_request_never_calls_llm(repository):
    llm = FakeLLM(error=AssertionError("must not be called"))
    response = await IntentParserService(repository, llm).parse("Get groceries")
    assert response.status == IntentStatus.RESOLVED
    assert response.intent.parse_method == ParseMethod.DETERMINISTIC
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_fuzzy_request_uses_structured_llm_then_canonical_catalog(repository):
    intent = IntentV1(
        original_text="ignored",
        required_errands=[IntentErrand(category="supermarket")],
        parse_method=ParseMethod.LLM,
        confidence=0.82,
    )
    llm = FakeLLM(intent=intent)
    service = IntentParserService(repository, llm)
    response = await service.parse("somewhere I can stock the pantry")
    assert response.status == IntentStatus.RESOLVED
    assert response.intent.required_errands[0].category == "groceries"
    assert response.intent.parse_method == ParseMethod.LLM
    assert response.diagnostics.input_tokens == 100
    assert service.metrics.snapshot().llm_parses == 1


@pytest.mark.asyncio
async def test_llm_cannot_invent_brand_or_location(repository):
    intent = IntentV1(
        original_text="ignored",
        required_errands=[
            IntentErrand(
                category="coffee", exact_brand="Imaginary Cafe",
                substitutes_allowed=False,
            )
        ],
        parse_method=ParseMethod.LLM,
    )
    response = await IntentParserService(repository, FakeLLM(intent=intent)).parse(
        "get that nice place from my dream"
    )
    assert response.status == IntentStatus.UNRESOLVED
    assert "Imaginary Cafe" in response.unresolved_terms
    assert response.intent is None


@pytest.mark.asyncio
async def test_llm_failure_returns_safe_structured_fallback(repository):
    service = IntentParserService(
        repository, FakeLLM(error=httpx.TimeoutException("bounded timeout"))
    )
    response = await service.parse("somewhere useful for the trip")
    assert response.status == IntentStatus.UNRESOLVED
    assert response.intent is None
    assert response.diagnostics.fallback_used
    assert response.diagnostics.validation_failures == 1


@pytest.mark.asyncio
async def test_openai_adapter_uses_strict_stored_false_structured_output(repository):
    output = IntentV1(
        original_text="ignored",
        required_errands=[IntentErrand(category="groceries")],
        parse_method=ParseMethod.LLM,
    ).model_dump_json()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        assert request.url.path == "/v1/responses"
        assert body["store"] is False
        assert "tools" not in body
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        assert body["text"]["format"]["schema"]["additionalProperties"] is False
        return httpx.Response(
            200,
            json={
                "output_text": output,
                "usage": {"input_tokens": 21, "output_tokens": 12, "total_tokens": 33},
            },
        )

    provider = OpenAIIntentProvider("test-only-key", "test-model")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="https://api.openai.com", transport=httpx.MockTransport(handler)
    )
    try:
        result = await provider.parse_intent(
            "stock up", repository.category_catalog(), repository.brand_catalog()
        )
    finally:
        await provider.close()
    assert result.intent.required_errands[0].category == "groceries"
    assert result.total_tokens == 33
