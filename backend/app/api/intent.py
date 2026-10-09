"""Natural-language requests: parsing into an intent, and the parser's metrics."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from app.config import Settings
from app.discovery_models import DiscoveryConfidence
from app.domain import Coordinate
from app.intent_models import (
    IntentMetricsSnapshot,
    IntentParseDiagnostics,
    IntentParseResponse,
    IntentStatus,
    JourneyConflict,
    JourneyMention,
)
from app.providers.base import (
    MapProvider,
    ProviderError,
)
from app.providers.mock import haversine_km
from app.schemas import IntentParseRequest
from app.services.discovery import NeedResolver
from app.services.intent_parser import IntentMetrics, IntentParserService
from app.services.journey_references import errand_only_text, extract_journey_references
from app.services.open_needs import open_category

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx's INFO request line includes the full URL. Some upstream APIs require
# credentials in query parameters, so never allow that logger to emit at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.api.responses import (
    discovery_context,
    hidden_fields,
)


def register(app: FastAPI, app_settings: Settings) -> None:
    internal_fields = hidden_fields(app_settings)

    @app.post("/api/intent/parse", response_model=IntentParseResponse, response_model_exclude=internal_fields)
    async def parse_intent(payload: IntentParseRequest, request: Request):
        parser: IntentParserService = request.app.state.intent_parser
        provider: MapProvider = request.app.state.provider
        references = extract_journey_references(payload.text)
        mentions: list[JourneyMention] = []
        conflicts: list[JourneyConflict] = []
        for reference in references:
            try:
                matches = await request.app.state.location_resolver.resolve(reference.text, limit=3)
            except ProviderError:
                matches = []
            match = matches[0] if matches and matches[0].confidence != DiscoveryConfidence.AMBIGUOUS else None
            mentions.append(JourneyMention(
                endpoint=reference.endpoint, text=reference.text,
                resolved_label=match.display_name if match else None,
                latitude=match.coordinate.latitude if match else None,
                longitude=match.coordinate.longitude if match else None,
            ))
            current = payload.origin if reference.endpoint == "origin" else payload.destination
            if current is not None:
                differs = match is None or haversine_km(
                    Coordinate(current.coordinate.latitude, current.coordinate.longitude),
                    match.coordinate,
                ) > 0.5
                if differs:
                    conflicts.append(JourneyConflict(
                        endpoint=reference.endpoint,
                        current_label=current.label,
                        mentioned_text=reference.text,
                        mentioned_label=match.display_name if match else None,
                        latitude=match.coordinate.latitude if match else None,
                        longitude=match.coordinate.longitude if match else None,
                        reason=(
                            f"Your {reference.endpoint} above is {current.label}, but your request "
                            f"mentions {match.display_name if match else reference.text}."
                        ),
                    ))
        errand_text = errand_only_text(payload.text, references)
        if not errand_text:
            return IntentParseResponse(
                status=IntentStatus.NEEDS_CLARIFICATION,
                unresolved_terms=[],
                clarification_question=(
                    "It looks like you're trying to change your destination. Update the To field instead."
                    if any(item.endpoint == "destination" for item in references)
                    else "I couldn't find an errand in that request. Try ‘KFC and bubble tea’, ‘buy toothpaste with minimal walking’, or ‘coffee if convenient’."
                ),
                diagnostics=IntentParseDiagnostics(clarification_required=True),
                journey_mentions=mentions,
                journey_conflicts=conflicts,
            )
        parsed = await parser.parse(errand_text, correction=payload.correction)
        resolver: NeedResolver = request.app.state.need_resolver
        open_needs = resolver.parse_open_needs(errand_text)
        parsed_count = len(parsed.intent.required_errands + parsed.intent.optional_errands) if parsed.intent else 0
        # More clauses than errands is only a sign of something missed when a
        # clause is one the parser did not understand: "milk and eggs" is two
        # clauses and one groceries errand, and was thrown away for discovery.
        uncovered = [
            need for need in open_needs
            if not parser.deterministic.understands(need.normalized_text)
        ]
        needs_open_discovery = parsed.status == IntentStatus.UNRESOLVED or (
            len(open_needs) > parsed_count and bool(uncovered)
        )
        if needs_open_discovery and open_needs:
            from app.intent_models import IntentErrand, IntentV1, ParseMethod

            search_context = discovery_context(payload.origin, payload.destination)
            discoveries = [
                await resolver.resolve(
                    need.raw_text, allow_live=True, context=search_context, open_need=need,
                )
                for need in open_needs
            ]
            required: list[IntentErrand] = []
            optional: list[IntentErrand] = []
            unresolved_terms: list[str] = []
            for index, discovery in enumerate(discoveries):
                if not discovery.places or not discovery.open_need:
                    unresolved_terms.append(discovery.original_query)
                    continue
                errand = IntentErrand(
                    category=open_category(discovery.open_need.normalized_text, index),
                    required=not discovery.open_need.optional,
                    substitutes_allowed=discovery.open_need.substitution_allowed,
                    discovery_concept=discovery.canonical_concept or discovery.original_query,
                    open_need=discovery.open_need,
                    discovery_category=discovery.category,
                )
                (optional if discovery.open_need.optional else required).append(errand)
            if required or optional:
                partial_message = (
                    "Found options for the other errand, but couldn't reliably find "
                    + ", ".join(unresolved_terms) + ". You can continue with what was found or edit the missing item."
                    if unresolved_terms else None
                )
                parsed = IntentParseResponse(
                    status=IntentStatus.RESOLVED,
                    intent=IntentV1(
                        original_text=errand_text, required_errands=required,
                        optional_errands=optional, parse_method=ParseMethod.DETERMINISTIC,
                        confidence=min((0.9 if item.places else 0.7) for item in discoveries),
                    ),
                    unresolved_terms=unresolved_terms,
                    clarification_question=partial_message,
                    diagnostics=IntentParseDiagnostics(
                        parser_latency_ms=sum(item.latency_ms for item in discoveries),
                        fallback_used=True, clarification_required=bool(unresolved_terms),
                    ),
                )
            else:
                parsed = IntentParseResponse(
                    status=IntentStatus.NEEDS_CLARIFICATION,
                    unresolved_terms=[item.original_query for item in discoveries],
                    clarification_question=(
                        "We couldn't find a reliable place for "
                        + " and ".join(f"'{item.original_query}'" for item in discoveries)
                        + ". Try a broader category, edit the request, or retry current places."
                    ),
                    diagnostics=IntentParseDiagnostics(
                        parser_latency_ms=sum(item.latency_ms for item in discoveries),
                        fallback_used=True, clarification_required=True,
                    ),
                )
        question = parsed.clarification_question
        status = parsed.status
        if conflicts:
            status = IntentStatus.NEEDS_CLARIFICATION
            question = conflicts[0].reason
        elif references and any(item.resolved_label is None for item in mentions):
            status = IntentStatus.NEEDS_CLARIFICATION
            question = "I found a journey change, but could not resolve that Singapore location. Please update the From or To field directly."
        return parsed.model_copy(update={
            "status": status, "clarification_question": question,
            "journey_mentions": mentions, "journey_conflicts": conflicts,
        })

    @app.get("/api/intent/metrics", response_model=IntentMetricsSnapshot)
    async def intent_metrics(request: Request):
        # Internal token, cost and latency metrics are opt-in for public APIs.
        if not app_settings.expose_diagnostics:
            raise HTTPException(status_code=404, detail="Not found")
        metrics: IntentMetrics = request.app.state.intent_metrics
        return metrics.snapshot()
