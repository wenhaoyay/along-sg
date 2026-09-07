# Architecture and decisions

## System boundary

```text
Next.js browser
    │ same-origin JSON over /api/* (no provider/admin secret)
    ▼
FastAPI
    ├── LocationResolver ── LTA rail gazetteer → local entities → OneMap fallback
    ├── NeedResolver ── concepts → SQLite FTS5 → optional live place provider
    ├── IntentParserService
    │   ├── deterministic grammar
    │   └── optional structured LLM adapter ── canonical catalog validation
    ├── MapProvider
    │   ├── MockOneMapProvider
    │   └── OneMapProvider ── token manager ── OneMap
    ├── HubRepository ── SQLite hubs/outlets + indexed discovery metadata
    ├── Optimizer ── candidate generation → pruning → routing → scoring → ranking
    ├── AnalyticsRepository ── allowlisted anonymous events in separate SQLite
    └── static Next.js export in the private-beta container
```

## V0.7.1 product-integrity boundary

The browser never sends an unconfirmed location string to optimisation. `LocationField`
debounces normalized `/api/geocode` searches and retains only the selected display label,
address/type and coordinates. Provider IDs and raw OneMap fields remain adapter-internal.

Intent parsing now has a separate journey-reference pass. Deterministic origin/destination
phrases are removed from the errand clause, geocoded through `MapProvider`, compared with
the explicit resolved endpoints, and returned as `journey_mentions`/`journey_conflicts`.
Explicit fields remain authoritative and any conflict blocks routing until the user keeps
the field, accepts the resolved mention, or edits it.

Discovery is database-driven: populated categories and counts come from SQLite; catalog
search spans canonical names, aliases and original independent outlet names. This widens
discovery without widening routing because the existing category SQL, corridor filter,
hub consolidation, approximate detour pruning and hard request budget remain in place.

Consumer serialization passes through `app.presentation`. Raw `node/`, `way/` and
`relation/` suffixes are stripped, internal hub/source IDs are absent, and a missing
standalone place context becomes “Location details unavailable.” Recommendations lead
with the hub/place, then matching businesses. Detour breakdown separates routed extra
transport from configurable category dwell allowances without claiming unsupported
precision.

The main surface is a full-viewport side panel plus Leaflet map using the official OneMap
Default basemap (`/maps/tiles/Default/{z}/{x}/{y}.png`) and SLA attribution. The map is
spatial context only: origin, destination, stop markers and baseline/recommended geometry;
turn-by-turn navigation remains an external per-stop handoff.

The browser knows only `NEXT_PUBLIC_API_BASE_URL`. OneMap email, password, and access token exist only in backend process memory. This also keeps upstream response changes out of the frontend contract.

## Stage gates

### V0.1 — geocode and baseline public transport

Acceptance criteria:

- A provider interface owns all geocoding and public-transport routing calls.
- Real mode authenticates server-side and caches/refreshes the reported token expiry.
- Mock mode requires no external calls and returns deterministic geocode/routes.
- `/api/geocode` and `/api/journey` return normalized models.
- The standalone probe captures upstream PT JSON before live-schema claims are made.
- V0.1 tests pass before using the optimiser.

### V0.2 — one errand

Acceptance criteria:

- Matching hubs come from SQLite rather than a global POI query.
- A straight-line detour heuristic prunes the pool before expensive route calls.
- Each remaining A→stop→B branch is compared with the direct A→B baseline.
- Added duration, added walking, and added transfers feed one central scoring function.
- Candidate generation, pruning, scoring, and objective ranking are deterministic.

### V0.3 — two errands

Acceptance criteria:

- A hub containing both requested categories becomes one consolidated stop.
- Separate hubs are considered in both orders after bounded pruning.
- The API returns Best Overall, Fastest, and Least Walking objectives.
- Candidate counts, routing calls, and latency are logged.
- The responsive UI handles one or two errands and explains the baseline comparison.

### V0.6 — natural-language intent and preferences

- `IntentV1` is the only versioned semantic contract passed into intent-aware optimisation.
- High-confidence category, brand and preference phrases are parsed deterministically and offline.
- Fuzzy unresolved requests use an LLM only when explicitly configured; strict structured output is validated again against SQLite.
- Exact brands, explicit detour/walking/transfer limits and arrival constraints are hard; preferred brands, tolerance, urgency and consolidation alter central score weights/bonuses.
- Optional errands may be omitted and labelled `partial_option`; required errands are never dropped.
- The UI previews the interpretation before routing and retains the structured category picker.
- Semantic fixtures, mock tests and frontend checks pass before any later-stage scope.

### V0.7 — private beta productisation and measurement

- A first-time commuter can move from journey and natural-language errand input to a recommendation with one primary action and no account or tutorial.
- The primary result leads with incremental time, walking and transfers, explains its deterministic win, compares with the direct journey and exposes only meaningfully distinct alternatives.
- Foreground current-location access is optional; no continuous tracking or exact-location analytics exists.
- A locally random anonymous UUID and allowlisted event payload support comprehension, selection, navigation, feedback and return metrics without fingerprinting.
- The aggregate admin report is server-token protected, analytics expire after the configured retention window, and static UI plus API run from one single-instance Docker service with persistent SQLite storage.
- Mock regression, frontend build/lint, browser E2E, credential scan and deployment smoke checks pass before acceptance.

## Provider abstraction and OneMap authentication

`MapProvider` has two stable operations:

```python
async geocode(query, limit) -> list[GeocodeMatch]
async route_public_transport(start, end, departure) -> RouteResult
```

`OneMapTokenManager` serializes refresh with an async lock so concurrent requests do not all authenticate. It caches the access token until the reported expiry minus a configurable safety margin. `OneMapProvider` retries one request after a 401 or a token-related error payload. Tokens are never logged, persisted to SQLite, or returned through the API.

The official OneMap documentation states that search is authenticated, access tokens are returned with a Unix expiry timestamp, and routing uses `/api/public/routingsvc/route` with `routeType=pt`. The implementation still treats the detailed PT itinerary as an uncertain external contract.

## Probe-first PT normalization

`scripts/probe_onemap_pt.py` is deliberately standalone: it authenticates and records a sanitised raw response without importing the production normalizer. This preserves the order of evidence:

1. Run a real request when credentials are available.
2. Inspect the captured fixture and sanitisation.
3. Adjust `normalize_public_transport_response()` to match observed fields.
4. Add the captured shape to adapter tests without committing sensitive or overly precise journey data.
5. Run explicit integration tests.

The normalized `RouteResult` contains:

- total duration in minutes;
- walking time and walking distance;
- transfer count;
- normalized legs (mode, duration, distance, endpoint names);
- provider/schema metadata that is not used for optimisation.

The parser currently supports the OTP-style `plan.itineraries` structure documented by ecosystem examples and represented by the offline schema template. It has defensive fallbacks for duration, walking totals, and transfer calculation. This is not a substitute for a live probe.

### Known OneMap uncertainties

- Live PT parameter spelling/format and allowed values can change independently of this code.
- The exact itinerary time units and optional fields must be confirmed from the probe fixture.
- OneMap may return error information with HTTP 200 for some authentication failures.
- Transfer semantics may differ between itinerary-level counts and inferred transit-leg changes.
- Availability, quotas, coverage, and journey freshness are upstream concerns.
- The current in-memory token cache is per backend process; multiple workers would each acquire a token.

Real verification is therefore opt-in through `RUN_ONEMAP_INTEGRATION=true`, never part of the deterministic default suite.

## SQLite data model and hub consolidation

`hubs` stores a consolidated physical stop with one coordinate. `outlets` stores stores/categories within the hub. Candidate generation queries hubs that contain any requested category and loads all their outlets.

For two categories:

- a hub containing both creates one `consolidated=True` option;
- category-matching hubs at different locations create two-stop options;
- pair identity is deduplicated before routing;
- both travel orders are evaluated later because public-transport cost is directional.

This avoids routing separately to multiple shops inside the same mall/interchange. The seed intentionally stays small and reviewable; it is not claimed to be complete or continuously current.

## Candidate bounding and route-call control

Before calling a route provider, each candidate gets a Haversine proxy:

```text
straight-line detour = shortest(A → candidate stops → B) − straight-line(A → B)
```

Candidates above the configured cutoff are removed, then the closest `max_candidates` options remain. A per-optimisation in-memory segment cache prevents repeated calls for the same directed coordinate pair. Diagnostics count only actual provider calls, not cache hits.

This heuristic is used only for pruning; recommendations use routed values. It can discard a geometrically distant but transit-efficient hub, which is an accepted V0 trade-off.

## Scoring and ranking

All penalties live in `ScoringWeights`:

```text
overall = added_duration × detour_weight
        + added_walking × walking_weight
        + added_transfers × transfer_weight
```

Incremental values are clamped at zero relative to the direct baseline so an upstream estimate anomaly cannot produce a negative inconvenience reward.

Ranking objectives are deterministic with explicit tie-breakers:

- **Best Overall:** overall score → added duration → added walking.
- **Fastest:** added duration → overall score → added walking.
- **Least Walking:** added walking → added duration → overall score.

The same physical candidate may legitimately win multiple objectives. The API returns three labelled views rather than inventing distinct alternatives.

## API and error behavior

- `GET /api/geocode` returns matches from the active provider.
- `POST /api/journey` resolves text or coordinates and returns one normalized PT baseline.
- `POST /api/optimize` accepts one or two errands and returns the baseline, recommendations, and diagnostics.

Input errors return 422. Provider/normalization failures return 502 without exposing credentials or raw upstream bodies. CORS is limited to local Next.js development origins for this stage.

## Observability

One structured log line per optimisation records:

- generated candidate count;
- evaluated ordered-option count;
- real routing-call count after cache hits;
- end-to-end optimisation latency in milliseconds.

V0 intentionally avoids a metrics stack, tracing service, or production log pipeline.

## Security and deployment posture

This is a development-stage local application, not a production deployment. Secrets are environment-only, TLS verification remains enabled, upstream error bodies are not forwarded, and no credential is prefixed `NEXT_PUBLIC_`. SQLite is local and contains only curated public outlet data.

## Earlier V0.4 candidate list

- Capture a real sanitised PT fixture and harden the adapter against observed variants.
- Add departure time/date selection and multiple OneMap itineraries.
- Curate more hubs and add a data freshness/review workflow.
- Model in-hub dwell time, store opening hours, and interchange overhead.
- Explain why a candidate won and show near-miss alternatives.
- Add frontend unit tests and browser-level end-to-end flows.
- Add resilience policies such as timeouts per optimisation, upstream backoff, and request budgets.
- Decide whether production needs shared token caching, managed spatial storage, or route-matrix batching based on measured load.

## V0.4 hardening addendum

V0.4 introduces an explicit `OneMapNormalizer`; no optimizer, API serializer or UI code reads upstream field names. It normalizes optional times and geometry along with duration, walking, transfers and legs. The 2026-08-26 live capture verifies the `plan.itineraries` schema, second/metre units, Unix-millisecond timestamps, encoded-polyline geometry, walking totals and transfer semantics. Synthetic compatibility fixtures still cover defensive nested/nullable/GeoJSON/no-route shapes not observed live.

Provider failures now have typed boundaries for authentication, rate limiting, timeout, upstream failure, invalid responses and no routes. Only transient failures are retried, with a configurable finite retry count and bounded backoff.

Each optimization has soft/hard routing-call budgets. Actual provider attempts, cache hits, provider latency, pruned/evaluated candidates, total latency, no-route candidates and budget state are instrumented. The hard budget is checked before every uncached call.

Dwell duration is configured by category and included in total journey inconvenience. Live morning/evening experiments verified that OneMap uses departure time, so each onward segment is requested after travel arrival plus dwell. Providers without verified time support retain the explicit limitation path.

Hubs now carry three distinct identifiers: physical semantic type, transport/station area, and consolidation group. Same-place errands consolidate; stores in the same station area or within 500 metres remain separate stops with an explicit relationship; more distant stores are genuinely separate stops.

Live findings and acceptance status live in `docs/onemap-pt-contract.md`; the live diagnostic is `docs/live-optimization-diagnostic.md`.

## V0.5 POI intelligence and bounded scaling

V0.5 keeps SQLite after measuring a 6,192-outlet database. The schema adds canonical
brands/aliases, a hierarchical category table, multi-category outlets, source/source IDs,
opening hours, freshness, closure status, transport nodes and hub proximity. Existing
curated hub IDs and the `HubRepository` boundary remain compatible.

The OSM ingestion pipeline is Singapore-only, deterministic after capture and repeatable
from the attributed raw export. Unknown hours stay null; a source capture timestamp is not
misrepresented as a store-level field survey. Closed rows remain auditable but candidate
queries exclude them.

Candidate work is now raw POIs → category hubs → baseline route corridor/endpoints →
transit proximity → hub coverage/consolidation → approximate detour → route-budget
admission → normalized OneMap routes. Every count is returned in diagnostics and logged.
The raw database size cannot increase the configured final route-call set.

The LRU route key includes directed coordinates and a one-minute departure bucket; cache
TTL and capacity are configurable. Candidate concurrency has a semaphore and in-flight
deduplication, but defaults to one after a live limit of two caused persistent HTTP 429s.
The hard call limit remains authoritative.

Maximum reasonable routed detour is configurable. When every option exceeds it or cannot
be routed, the API returns `outcome=no_convenient_option` and an empty recommendation map.
Deterministic substitute-category near misses exist only in the internal model/count and
are not automatically exposed as recommendations.

## V0.6 intent boundary

Natural language ends at `IntentParserService`. `IntentV1` contains at most two errands,
split into required and optional lists, plus walking, transfer, detour, consolidation,
urgency and arrival preferences. Brand fields distinguish exact (hard, no substitution)
from preferred (soft, substitutes allowed). Every category and brand is resolved through
the local `categories`, `brands`, `brand_aliases` and `brand_categories` tables before the
optimizer can run.

The deterministic parser owns easy, auditable phrases. It returns clarification for
conflicting constraints and unresolved status for unsupported terms. Only the latter may
reach `OpenAIIntentProvider`, and only when both `LLM_INTENT_ENABLED=true` and a backend
API key are present. The adapter calls the Responses API with strict JSON schema,
`store=false` and no tools. Its output cannot name coordinates or routes and is discarded
if catalog validation fails. With no provider or on any bounded provider failure, the
service returns the deterministic clarification path.

`preferences_from_intent()` is the sole translation into `OptimizationPreferences`.
It applies configured score bonuses and explicit multipliers rather than modifying route
results. Candidate generation filters exact-brand requirements before routing. The
optimizer filters hard detour, added-walking, added-transfer and arrival limits after
routing. A preferred brand miss can be labelled `easier_alternative`; an optional errand
omission is labelled `partial_option`. A second required-only pass shares the original
hard request budget through a routing-call offset, so the HTTP request still cannot exceed
the configured hard ceiling.

Process-local metrics expose deterministic/LLM parse rates, latency, validation failures,
unresolved terms, fallbacks, clarifications, corrections, token counts and selected
alternative counts. Cost remains null unless the provider supplies measured cost; the
application does not estimate prices from a hard-coded model table.

Known limitations: the grammar intentionally covers a bounded Singapore errand domain;
free-form time phrases beyond the documented ISO arrival form generally need LLM help or
clarification. There is no conversation memory, opening-hours reasoning, model-created
POI, or model influence over routing. The V0.6 intent-parser diagnostic counters reset
with the backend process; persistent V0.7 beta events are described below.

## V0.7 private-beta boundary

The V0.7 UI preserves the V0.6 intent and optimizer boundaries but collapses parse and
optimization into one primary browser action. The parsed interpretation remains visible
and correctable. Results deduplicate identical physical alternatives and lead with added
time, added walking and added transfers; provider diagnostics and score internals stay out
of the beta interface. Navigation is an explicit hand-off to an external map rather than
turn-by-turn functionality.

Beta telemetry is deliberately independent from optimizer observability. The browser
generates random user/session/search/event UUIDs. `AnalyticsEventRequest` forbids unknown
fields, and the SQLite table has no place, coordinate, request-text, IP or user-agent
columns. Server time is authoritative, duplicate event UUIDs are idempotent, and startup
removes records older than the configured retention period. Metrics use distinct search
identifiers so client retries cannot inflate completion or selection rates. The admin
aggregate endpoint is absent unless a backend token is configured.

The deployment is a multi-stage Docker image: Next.js performs a static export, then one
FastAPI/uvicorn process serves that export and the API from one origin. The POI and
analytics databases live under one persistent `/data` mount. This is simpler and more
secure for a 30–50-person beta than two independently configured public services, but it
also enforces a single-instance ceiling. Moving to shared storage, multiple workers or a
production analytics platform is explicitly not part of V0.7.

## V0.7.2 consumer recommendation boundary

V0.7.2 replaces the earlier terminal detour filter with one bounded evaluation pipeline.
It computes the baseline once, admits a bounded exact candidate set, and can reuse that
request's segment cache and hard call budget for predeclared substitute or one-errand
fallbacks. The consumer ladder is: full exact match, exact match outside a soft preference,
allowed category substitute, useful partial, best available compromise, then genuine
failure. It does not launch an unbounded optimizer pass per relaxation level. Explicit
brand/place requirements are retained in every relevant fallback and are never
substituted. A result outside an explicit hard limit is returned only as an unmet
`closest_option`; the API never calls it a satisfied recommendation.

`OptimizationPreferences` carries separate values and `*_is_hard` flags. The deterministic
parser maps “must”, “only”, “specifically”, “do not substitute” and a stated “max” to hard
semantics. “Prefer”, “ideally” and “try to keep under” remain soft. Structured discovery
uses the same model through explicit Any, Preferred and Required choices. Internal
reasonable-detour thresholds now change the classification to `best_available` instead
of deleting all routed options.

The ranking score remains centralized. A configurable `data_quality_bonus` subtracts at
most a small minute-equivalent bonus according to deterministic location/actionability
quality, so it can resolve near ties without overcoming a clearly better journey. Location
context uses this evidence order: explicit address; the hub itself when it is a mall;
associated station area; a separately captured mall within 350 metres; associated station
with distance; nearest named Singapore area. The 350-metre association is computed from
source coordinates and presented as “Near”, never as a containing-mall claim. Reverse
geocoding is deliberately deferred because it would consume extra live requests inside
the existing route budget. Coordinates remain required for navigation handoff.

Search uses SQLite NOCASE indexes and one bounded backend query across categories, brands,
aliases and independent places. The response boundary strips raw OSM node/way/relation
suffixes and deduplicates cleaned labels. The browser waits 250 ms after typing and requests
at most 12 results; it does not render the full catalog.

The map uses OneMap's official GreyLite XYZ style (zoom 11–19) and retains OneMap/SLA
attribution. This is a visual style change, not a provider migration, and avoids treating
the public OpenStreetMap tile service as a production CDN. Map state is journey-driven:
Singapore overview before selection, origin focus after From, A/B bounds after both
endpoints, and A → numbered stop(s) → B plus baseline/recommended geometry after results.
Baseline is dashed neutral grey and the recommendation is solid green.

Objective views are deduplicated by ordered stop IDs and rounded detour/walking/transfer
signature. The consumer UI shows only genuinely different alternatives, human quality
labels, location context and an inconvenience/dwell breakdown. Routing-call counts,
candidate counts, scores and provider terminology remain in logs and API diagnostics,
not in result cards. Benchmark evidence is in `docs/v072-benchmark-mock.json`; manual and
browser evidence is in `docs/v072-manual-qa.md`.

## V0.7.2-UI presentation boundary

The presentation layer now treats the OneMap map as the persistent spatial canvas. On
desktop, the input or recommendation appears as a compact floating card; at 820 pixels
and below, the same state becomes a bounded bottom sheet that leaves the journey visible.
The planner swaps in place between input and result instead of navigating or scrolling to
a second page. This is a component and CSS reorganization only: request payloads,
normalized route models, fallback policy and optimizer ranking are unchanged.

The visual system uses the existing Along green as its sole strong accent, near-white
surfaces, system sans-serif typography, 18–20 pixel container radii and restrained
150–240 ms transitions. Lucide supplies tree-shakeable interface icons; no Apple assets,
branding or proprietary fonts are included. `prefers-reduced-motion` disables transitions
and route-camera animation.

Progressive disclosure keeps the default result to one recommendation, added time,
walking, transfers, the errand stop and one navigation action. Rationale, dwell detail and
genuinely distinct alternatives use native `details` elements. Provider diagnostics,
candidate language and score internals remain absent from consumer copy. Location inputs
retain explicit selection and now expose combobox/listbox state plus Arrow, Enter and
Escape keyboard behaviour.

Visual capture is deterministic: Playwright intercepts APIs and map tiles and records the
seven required states at 1440×900 and 390×844 only when `CAPTURE_VISUALS=1`. The ordinary
suite skips capture, so CI does not create local artifacts. Screenshots are ignored under
`outputs/v072-ui-screenshots/`; review findings and the viewport matrix are documented in
`docs/v072-ui-manual-qa.md`.

## V0.7.4 open-world discovery boundary

Plausible errand validity no longer depends on the catalog taxonomy. `OpenNeed` is carried
inside `IntentErrand`, and request-scoped `open_*` categories prevent broad catalog matches
from entering the optimiser. Only normalized, coordinate-bearing `ResolvedPlace` objects
with supported-or-better structured evidence become transient hubs. Web results are names
and snippets only until separately grounded; upstream field names never cross provider
adapters.

Discovery escalates local FTS → deterministic/optional LLM semantics → TomTom → Geoapify →
Tavily → grounding. Each stage has a per-need budget and failures are isolated. Route
geometry is obtained through `Optimizer.prepare_discovery_context()`, cached under the same
time-aware route key used by optimisation, and shared as corridor context. Same-mall live
places consolidate into one hub with multiple need-specific stores; nearby names without a
shared mall remain separate.

See `docs/open-world-discovery.md` for provider contracts, evidence tiers, inventory/menu
semantics, cache/attribution rules, privacy and the 272-query evaluation method.
