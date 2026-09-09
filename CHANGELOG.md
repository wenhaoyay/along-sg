# Changelog

This file keeps the development milestones out of the main README while preserving the project's progression.

## 0.7.7 — Honest headline numbers, dark mode and offline shell

Suppressed alternatives whose journey is indistinguishable from the
recommendation - within 2 minutes, 100 m and the same transfer count - so a
second mall is offered only when it is a real choice; an alternative that reads
better on the headline number now states what it costs. Moved the headline from
total added time to extra travel, with in-store time disclosed separately,
because dwell is near-constant across options and was compressing the
difference between them. Collapsed the per-shop opening-hours caveat into one
line when a stop's shops share a state. Added a full dark palette driven by
`prefers-color-scheme`, including inverted map tiles, and tokenised every
remaining hardcoded colour to make it possible; an app-bar button cycles
auto/light/dark, persists the choice and overrides the device, with a blocking
bootstrap script so an override paints correctly on first frame. Added a web manifest, icons and
a service worker so the app installs and its shell opens offline; nothing under
`/api/` is ever cached or replayed, because a stale recommendation is worse than
an error. Renamed the direct-route label from "Straight" to "Direct".

## 0.7.6 — Transit graph coverage and network-aware pruning

Fixed an Overpass transform defect that discarded every way and relation, restoring 244
of 250 mall polygons and 327 further outlets. Widened the capture to bus stops, taking
the transport graph from 132 rail-only nodes to 5,978 and the share of hubs beyond
1,200 m of any node from 45.6% to 0.2%; `station_area` still requires rail within 150 m.
Ranked candidates for the routing budget by distance from the baseline route plus
transit access walk rather than by great-circle distance from the origin-destination
chord. Raised routing concurrency to 4 and the candidate/budget ceilings to match.
Ingested hubs now supersede the curated seed for the same building instead of competing
with it, and prefixed source ids no longer leak into display names.

## 0.7.5 — September journey and discovery improvements

Added Singapore-time departure planning, arrival-aware opening-hours warnings, cancellable/retryable searches, route-proximity candidate ranking, stricter business grounding, related-search recovery, journey timeline/map synchronization, clearer recommendation explanations, mobile result controls and a repeatable six-case offline benchmark.

## 0.7.4 — Open-world discovery

Added plausible free-form need parsing, independent compound resolution, route-corridor place search, bounded TomTom/Geoapify/Tavily escalation and offline discovery evaluation.

## 0.7.3 — Discovery intelligence

Separated location and need resolution, added the LTA rail gazetteer and aliases, SQLite FTS5 search, structured concepts and confidence-triggered live place search.

## 0.7.2 — Consumer UI and fallback behavior

Added the map-first interface, clearer recommendation states, bounded fallback ladder, preference semantics, deterministic location context and more robust alternative ranking.

## 0.7.1 — Product integrity

Added explicit location selection, journey-conflict handling, database-driven catalog search, safer consumer serialization and clearer detour breakdowns.

## 0.7 — Private beta

Added the natural-language workflow, current-location option, anonymous allowlisted analytics, feedback, browser E2E coverage and single-container deployment.

## 0.6 — Intent layer

Added structured intent, deterministic parsing, optional schema-validated LLM fallback and preference-aware scoring.

## 0.5 — POI intelligence

Added the Singapore OSM POI corpus, taxonomy/aliases, mall and transit-node intelligence, staged corridor pruning and route caching.

## 0.4 — Routing hardening

Added OneMap normalization, bounded retries, request budgets, live-contract fixtures, time-aware routing checks and routing diagnostics.

## 0.3 — Two errands

Added same-hub consolidation, separate-stop ordering and objective-specific ranking.

## 0.2 — One errand

Added candidate generation, geometric pruning, branch routing and incremental scoring against the direct journey.

## 0.1 — Baseline journey

Added the OneMap provider abstraction, backend authentication/token caching, geocoding and normalized public-transport journey results with deterministic mock mode.
