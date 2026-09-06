from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.intent_models import IntentV1, ParseMethod


@dataclass(frozen=True)
class LLMIntentResult:
    intent: IntentV1
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class IntentLLMProvider(Protocol):
    async def parse_intent(
        self,
        text: str,
        categories: tuple[str, ...],
        brands: tuple[dict[str, Any], ...],
    ) -> LLMIntentResult: ...


def _strict_schema(model: type[IntentV1]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                properties = node.get("properties", {})
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


class OpenAIIntentProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 20.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def parse_intent(
        self,
        text: str,
        categories: tuple[str, ...],
        brands: tuple[dict[str, Any], ...],
    ) -> LLMIntentResult:
        catalog = {
            "categories": categories,
            "brands": [
                {"name": brand["canonical_name"], "categories": brand["categories"]}
                for brand in brands
            ],
        }
        instructions = (
            "Extract only the user's errand intent. Use only categories and canonical brands "
            "from the supplied catalog. Never invent a place, outlet, route, travel time, or "
            "opening hours. Preserve hard words such as must, only, specifically and don't "
            "substitute as exact_brand with substitutes_allowed=false. A preference that "
            "explicitly allows alternatives is preferred_brand. Put if-convenient/skip-if-hard "
            "errands in optional_errands. Return schema_version 1.0, parse_method llm, and the "
            "original user text. If a term cannot be represented, do not guess a nearby brand."
        )
        payload = {
            "model": self.model,
            "store": False,
            "instructions": instructions,
            "input": json.dumps({"catalog": catalog, "request": text}, ensure_ascii=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "singapore_journey_intent_v1",
                    "strict": True,
                    "schema": _strict_schema(IntentV1),
                }
            },
        }
        started = time.perf_counter()
        response = await self.client.post(
            f"{self.base_url}/responses",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        body = response.json()
        output_text = body.get("output_text")
        if not output_text:
            for item in body.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
        if not isinstance(output_text, str):
            raise ValueError("LLM response did not contain structured output text")
        intent = IntentV1.model_validate_json(output_text).model_copy(
            update={"original_text": text, "parse_method": ParseMethod.LLM}
        )
        usage = body.get("usage") or {}
        return LLMIntentResult(
            intent=intent,
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            cost_usd=None,
        )
