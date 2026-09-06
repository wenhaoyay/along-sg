from __future__ import annotations

import json
import time
from typing import Protocol

import httpx

from app.discovery_models import (
    DiscoveryConfidence,
    NeedSemanticType,
    OpenNeed,
    SemanticExpansion,
)


class SemanticExpansionProvider(Protocol):
    calls: int

    async def expand(self, need: OpenNeed) -> SemanticExpansion: ...


class OpenAISemanticExpansionProvider:
    """Optional concept expansion only; it is forbidden from authoritatively naming businesses."""

    def __init__(self, api_key: str, model: str, base_url: str, timeout_seconds: float):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self.calls = 0

    async def expand(self, need: OpenNeed) -> SemanticExpansion:
        self.calls += 1
        schema = {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": [item.value for item in NeedSemanticType]},
                "canonical_term": {"type": "string"},
                "generic_term": {"type": ["string", "null"]},
                "likely_place_types": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                "related_search_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                "category_hint": {"type": ["string", "null"]},
            },
            "required": ["type", "canonical_term", "generic_term", "likely_place_types", "related_search_terms", "category_hint"],
            "additionalProperties": False,
        }
        payload = {
            "model": self._model, "store": False,
            "instructions": (
                "Classify and expand a plausible everyday Singapore errand. Return concepts and place types only. "
                "Never name or invent businesses, outlets, coordinates, stock, routes, or opening hours."
            ),
            "input": need.raw_text,
            "text": {"format": {"type": "json_schema", "name": "open_need_expansion", "strict": True, "schema": schema}},
        }
        started = time.perf_counter()
        response = await self._client.post(
            f"{self._base_url}/responses",
            headers={"Authorization": f"Bearer {self._api_key}"}, json=payload,
        )
        latency = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        body = response.json()
        output = body.get("output_text")
        if not output:
            output = next((content.get("text") for item in body.get("output", []) for content in item.get("content", []) if content.get("type") == "output_text"), None)
        if not isinstance(output, str):
            raise ValueError("Semantic expansion did not return structured output")
        value = json.loads(output)
        usage = body.get("usage") or {}
        return SemanticExpansion(
            semantic_type=NeedSemanticType(value["type"]), canonical_term=value["canonical_term"],
            generic_term=value["generic_term"], likely_place_types=tuple(value["likely_place_types"]),
            related_search_terms=tuple(value["related_search_terms"]), category_hint=value["category_hint"],
            confidence=DiscoveryConfidence.LIKELY, method="llm", latency_ms=latency,
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
        )

    async def close(self) -> None:
        await self._client.aclose()


class MockSemanticExpansionProvider:
    def __init__(self, fixtures: dict[str, SemanticExpansion] | None = None):
        self.fixtures = fixtures or {}
        self.calls = 0

    async def expand(self, need: OpenNeed) -> SemanticExpansion:
        self.calls += 1
        if need.normalized_text not in self.fixtures:
            raise ValueError("No mock semantic expansion")
        return self.fixtures[need.normalized_text]
