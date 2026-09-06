from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class JourneyReference:
    endpoint: str
    text: str
    span: tuple[int, int]


_ORIGIN_PATTERNS = (
    r"\b(?:i(?:'m| am)\s+)?(?:leaving|starting)\s+(?:from|at)\s+(.+?)(?=\s+(?:and|then)\b|[,.]|$)",
    r"\borigin(?:\s+is|:)\s*(.+?)(?=\s+(?:and|then)\b|[,.]|$)",
)
_DESTINATION_PATTERNS = (
    r"\b(?:reach|go)\s+home\s+(?:at|to)\s+(.+?)\s*$",
    r"\b(?:then\s+)?(?:go|head)(?:\s+home)?(?:\s+to)?\s+(.+?)\s*$",
    r"\b(?:destination|end|finish)(?:\s+at|\s+is|:|\s+)\s*(.+?)(?=[,.]|$)",
    r"\binstead\s+go\s+(?:to\s+)?(.+?)\s*$",
)


def extract_journey_references(text: str) -> tuple[JourneyReference, ...]:
    found: list[JourneyReference] = []
    for endpoint, patterns in (("origin", _ORIGIN_PATTERNS), ("destination", _DESTINATION_PATTERNS)):
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip(" .,!?")
            if value:
                found.append(JourneyReference(endpoint, value, match.span()))
                break
    return tuple(found)


def errand_only_text(text: str, references: tuple[JourneyReference, ...]) -> str:
    cleaned = text
    for reference in sorted(references, key=lambda item: item.span[0], reverse=True):
        start, end = reference.span
        cleaned = cleaned[:start] + " " + cleaned[end:]
    return re.sub(r"\s+", " ", cleaned).strip(" ,.;")
