# Along the Way — Singapore journey-aware errand optimiser

V0.1–V0.7.4 of a mobile-first optimiser that fits one or two errands into an existing Singapore public-transport journey. The backend resolves ordinary Singapore place/need language before comparing real POI/hub candidates against a direct A→B baseline.

The app runs fully offline by default with deterministic OneMap-compatible mocks. OneMap credentials remain backend-only.

The September UX refinements add Singapore-time departure planning, cancellable/retryable searches, a selectable stop timeline, mobile sheet positions, conservative opening-hours warnings and stricter discovery evidence. See [implementation and benchmark notes](docs/remaining-recommendations-september.md) and [opening-hours limitations](docs/smarter-results-september.md). Live/manual quality acceptance is still outstanding; offline benchmark results are not real-world relevance scores.

## What is included

- **V0.1:** OneMap provider abstraction, server-side authentication/token caching, geocoding, and normalized public-transport journey results in real or mock mode.
- **V0.2:** One-errand candidate generation, bounded geometric pruning, branch routing, incremental metrics, and configurable scoring.
- **V0.3:** Two-errand candidates, same-hub consolidation, both stop orders for separate hubs, objective-specific ranking, and optimisation diagnostics.
- **V0.4 hardening:** Isolated OneMap normalization, bounded failure retries, request budgets, cache/provider-latency instrumentation, category dwell time, verified time-aware routing, richer stop semantics, a 24-request live contract capture, five representative routes, and live one/two-errand diagnostics.
- **V0.5 POI intelligence:** 6,162 Singapore OpenStreetMap POIs, canonical chain aliases, hierarchical categories, source/freshness/hours/closure metadata, mall and transit-node intelligence, staged corridor pruning, time-aware LRU route caching, explicit no-convenient-option results, internal near misses, and mock/live benchmarks.
- **V0.6 intent layer:** Versioned structured intent, deterministic high-confidence parsing, an optional schema-validated LLM fallback for fuzzy language, canonical catalog validation, hard/soft/optional preference semantics, intent-aware scoring, and interpretation instrumentation.
- **V0.7 private beta:** One-action natural-language workflow, foreground-only current location, inconvenience-first recommendation, useful alternatives, anonymous allowlisted analytics, feedback, aggregate admin reporting, error recovery, browser E2E coverage and a single-container deployment.
- **V0.7.1 product quality:** Explicit debounced location resolution, journey-reference conflict blocking, nonsense/destination-only handling, database-driven catalog discovery, independent POIs, expanded OSM taxonomy, raw-ID presentation guards, hub-first recommendations, detour breakdowns and a full-screen OneMap utility UI.
- **V0.7.2 consumer polish:** A bounded exact → soft-limit → substitute → partial → best-available fallback ladder, explicit Any/Preferred/Required semantics, deterministic location context, near-tie data-quality ranking, honest quality labels, deduplicated alternatives, unified discovery, route-focused map framing and a calmer responsive interface.
- **V0.7.2-UI presentation:** A content-first, full-canvas OneMap experience with a compact desktop journey card, mobile bottom sheet, progressive recommendation details, keyboard-friendly autocomplete, restrained motion and a single prominent action per state. It applies Apple-inspired clarity and restraint without using Apple assets, branding or proprietary fonts.
- **V0.7.3 discovery intelligence:** Separate typed location/need resolvers, a 200-station official LTA rail gazetteer with 1,235 aliases, SQLite FTS5 over richer OSM metadata, structured dish/product/service concepts, optional confidence-triggered TomTom search, cross-source deduplication and ephemeral confirmed-place optimisation.
- **V0.7.4 open-world discovery:** First-class plausible `OpenNeed` parsing, independent compound resolution, conservative product/dish semantics, structured place evidence, route-corridor search, bounded TomTom → Geoapify → Tavily escalation, mandatory web grounding, optional concept-only LLM expansion and a 272-query offline evaluation.
- **Frontend:** Responsive Next.js/TypeScript journey panel plus OneMap spatial context, with a compact interpretation preview, secondary searchable catalog, place-first results and per-stop navigation hand-off.
- **Data:** SQLite with 6,199 imported/curated outlets; the bundled capture populates 18 consumer categories after V0.7.1 reingestion. OSM data © OpenStreetMap contributors, ODbL 1.0.

Out of scope for this stage: LLM control of routes or place invention, accounts, payments, realtime LTA feeds, PostGIS, turn-by-turn navigation, background GPS, social features, and production-scale infrastructure.

## Repository layout

```text
backend/
  app/                 FastAPI app, provider adapters, optimiser, SQLite repository
  fixtures/            Offline PT response schema template
  scripts/             Explicit live OneMap PT probe
  tests/               Stage and integration tests
frontend/
  app/                 Next.js App Router UI and privacy notice
  e2e/                 Playwright mobile/desktop journeys and visual-state capture
docs/architecture.md   Decisions, contracts, uncertainties, and stage criteria
```

## Quick start (mock mode)

Prerequisites: Python 3.12+, Node.js 20.9+ (Node 24 was used for verification), and npm.

1. Copy `.env.example` to `.env` at the repository root, or export the values in your shell. The backend loads that root file without overriding existing environment values. `ONEMAP_MOCK=true` is the default even without a file. For a non-default browser API URL, also put `NEXT_PUBLIC_API_BASE_URL=...` in `frontend/.env.local` before building the frontend.

2. Start the backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

On macOS/Linux, activate with `source .venv/bin/activate`.

3. In another terminal, start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. In mock mode, choose confirmed autocomplete suggestions before searching; no unresolved text is silently routed.

The V0.7.2-UI review matrix and screenshot workflow are documented in `docs/v072-ui-manual-qa.md`.

## API

Interactive OpenAPI documentation is available at `http://localhost:8000/docs` while the backend is running.

### `GET /api/geocode?q=BP9`

Returns layered Singapore matches from the local LTA gazetteer, local hubs and OneMap fallback, including confidence and station-code/line context. Ambiguous results require explicit selection.

### `GET /api/discovery/needs?q=mee%20pok`

Creates an open need even when the phrase is outside the static taxonomy, classifies a brand, independent business, category, cuisine, dish, product, service or place type, searches indexed local evidence, and optionally escalates through bounded backend-only place/web providers. The response exposes evidence tier and product suitability but no raw provider IDs. Web candidates must be grounded to real coordinates before optimisation. Confirmed live coordinates remain ephemeral.

### Catalog discovery

`GET /api/catalog/categories` returns populated taxonomy categories with outlet counts. `GET /api/catalog/search?q=...&category=...` performs an indexed, bounded search across categories, canonical brands, aliases and independent place names without returning provider/database identifiers. The browser debounces this single discovery surface and shows at most 12 initial matches.

### `POST /api/journey`

```json
{
  "origin": { "query": "Punggol MRT" },
  "destination": { "query": "Orchard MRT" }
}
```

A location can instead use a coordinate:

```json
{ "coordinate": { "latitude": 1.4052, "longitude": 103.9024 } }
```

### `POST /api/optimize`

```json
{
  "origin": { "query": "Punggol MRT" },
  "destination": { "query": "Orchard MRT" },
  "errands": ["groceries", "pharmacy"]
}
```

Supported categories come from the populated backend catalog. The bundled capture currently adds burgers, Japanese, Korean and Chinese food, bakeries, dessert and optical POIs beyond the original set; broader mappings appear only where captured OSM data supports them.

### `POST /api/intent/parse`

```json
{ "text": "Prefer KFC but another fried chicken is okay, under 20 minutes" }
```

Returns a versioned `IntentV1` preview or a clarification request. Unknown-but-plausible phrases remain valid `OpenNeed` values, and up to two compound clauses resolve independently. With resolved From/To context, journey mentions are returned separately and endpoint conflicts block optimisation. Pure journey instructions and non-errands return specific guidance. Optional LLM expansion can classify an unknown concept but cannot authoritatively create places.

### `POST /api/optimize-intent`

Accepts the normal origin/destination/departure fields plus a previewed `intent`. “Must/only/required” brands and limits stated with “max” are required; “prefer/ideally/try to keep under” remain preferences. Preferred brands may produce a category-valid easier alternative, while required brands are never substituted. Optional or useful single-errand results can be labelled `partial_option`. If an internal convenience range is exceeded, the least disruptive routed match is returned as `best_available` instead of erased. A result exceeding the user's explicit maximum is informationally labelled `closest_option` and marked unmet.

### Beta analytics

`POST /api/analytics/events` accepts only the V0.7 allowlisted anonymous event schema—no coordinates or free-form text. `GET /api/admin/analytics` returns an aggregate report only when `BETA_ADMIN_TOKEN` is configured and supplied as a Bearer token; otherwise the endpoint is hidden. See [the privacy note](docs/privacy.md) and [private-beta operations](docs/private-beta-operations.md).

## POI ingestion

The attributed Singapore-only OSM export is included at `backend/data/singapore-osm-pois.json`. Rebuild the local ignored SQLite database without network access:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ingest_osm_pois.py --input data\singapore-osm-pois.json
```

Omitting `--input` performs a fresh bounded Overpass download. See `backend/data/README.md` and `docs/v05-data-and-benchmarks.md` for licensing, coverage and benchmark evidence.

## Real OneMap mode

Register credentials through the [official OneMap API portal](https://www.onemap.gov.sg/apidocs/). Keep them only in the backend environment:

```powershell
$env:ONEMAP_MOCK = "false"
$env:ONEMAP_EMAIL = "registered-email"
$env:ONEMAP_PASSWORD = "registered-password"
uvicorn app.main:app --reload --port 8000
```

Do not add credentials to `NEXT_PUBLIC_*` values. The backend obtains a token from OneMap, caches it in memory until shortly before its reported expiry, refreshes it when needed, and retries once after token-related failures.

### Probe the public-transport schema first

OneMap's public-transport payload remains isolated behind the provider adapter. With backend credentials present, run:

```powershell
cd backend
python scripts/probe_onemap_pt.py
```

This runs a hard-bounded request-contract matrix plus five representative journeys and writes sanitised fixtures under `backend/fixtures/live/<capture-date>/`, including a manifest. Authentication responses and headers are never persisted. Review the fixtures against `OneMapNormalizer` before changing or claiming the real adapter is verified. See `docs/onemap-pt-contract.md`.

The definitive sanitised live capture is under `backend/fixtures/live/2026-08-26T195357/`. Synthetic fixtures remain marked `captured_live: false` and continue to cover defensive shapes that were not observed live. See `docs/onemap-pt-contract.md` for accepted/rejected parameters, verified units and actual route modes.

After reviewing the contract, produce the bounded one- and two-errand comparison:

```powershell
python scripts/run_live_optimizations.py
```

This writes `docs/live-optimization-diagnostic.md` without credentials or tokens.

## Configuration

All scoring contributions are configured centrally as minute-equivalents:

| Environment variable | Default | Meaning |
|---|---:|---|
| `OPTIMIZER_DETOUR_WEIGHT` | `1.0` | Weight for added total journey minutes |
| `OPTIMIZER_WALK_WEIGHT` | `0.65` | Weight for added walking minutes |
| `OPTIMIZER_TRANSFER_WEIGHT` | `6.0` | Penalty per added transfer |
| `OPTIMIZER_PREFERRED_BRAND_BONUS` | `2.0` | Score bonus when a preferred brand is satisfied |
| `OPTIMIZER_CONSOLIDATED_STOP_BONUS` | `1.0` | Score bonus when requested consolidation is satisfied |
| `OPTIMIZER_DATA_QUALITY_BONUS` | `2.5` | Small near-tie bonus for an addressable, clearly identified stop |
| `OPTIMIZER_MAX_CANDIDATES` | `4` | Maximum approximate-detour options before route-budget admission |
| `OPTIMIZER_MAX_STRAIGHT_LINE_DETOUR_KM` | `12` | Geometric pre-routing cutoff |
| `OPTIMIZER_ROUTING_SOFT_BUDGET` | `10` | Warn once after this many real routing calls |
| `OPTIMIZER_ROUTING_HARD_BUDGET` | `12` | Absolute per-optimisation routing-call ceiling |
| `OPTIMIZER_MAX_REASONABLE_DETOUR_MINUTES` | `45` | Quality-label boundary; does not erase an otherwise valid routed option |
| `OPTIMIZER_ROUTING_CONCURRENCY` | `1` | Conservative candidate-routing concurrency; live `2` triggered 429s |

Category dwell variables are `DWELL_GROCERIES_MINUTES`, `DWELL_PHARMACY_MINUTES`, `DWELL_PARCEL_MINUTES`, `DWELL_ELECTRONICS_MINUTES`, and `DWELL_BANKING_MINUTES`. Dwell is always included in total inconvenience. It advances onward segment departure time only when the provider's live departure-time behaviour is explicitly verified.

The API logs generated/evaluated candidate counts, actual routing-call count, and total optimisation latency. Technical diagnostics remain available to development clients but are not displayed in the consumer interface.

Evaluate the deterministic open-world parser and local evidence layer without network access:

```powershell
cd backend
.\.venv\Scripts\python.exe tools\evaluate_open_world_discovery.py
```

If `TOMTOM_API_KEY` and/or `GEOAPIFY_API_KEY` is configured, the secret-free bounded provider comparison is available as `tools\compare_live_discovery.py`. Missing keys produce an explicit `not_run` result; they do not disable local development.

### Optional LLM fallback

Offline deterministic parsing is the default. To explicitly enable the backend-only fallback, set `LLM_INTENT_ENABLED=true` and `OPENAI_API_KEY` in the root `.env`. The adapter uses the Responses API with strict JSON-schema output, `store=false`, no tools, and no route or place authority. Never expose the key through a `NEXT_PUBLIC_*` variable. Live LLM tests additionally require `RUN_LLM_INTEGRATION=true`.

### Optional live place discovery

Local/LTA/OSM discovery is the default and needs no account. Set `DISCOVERY_LIVE_ENABLED=true` with `TOMTOM_API_KEY` for the primary place provider and/or `GEOAPIFY_API_KEY` for the secondary. Set `DISCOVERY_WEB_ENABLED=true` with `TAVILY_API_KEY` only for grounded long-tail web evidence. `DISCOVERY_SEMANTIC_LLM_ENABLED=true` reuses the backend-only OpenAI configuration for one concept-only expansion call. Missing keys disable each adapter cleanly. Results use a five-minute in-memory cache and are not written to SQLite. See [the V0.7.4 provider and evidence report](docs/open-world-discovery.md) before enabling any provider.

Rebuild and evaluate discovery locally:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ingest_osm_pois.py --input data\singapore-osm-pois.json
.\.venv\Scripts\python.exe tools\evaluate_discovery.py --database data\errands.db
.\.venv\Scripts\python.exe tools\evaluate_open_world_discovery.py
```

## Tests and verification

Run the deterministic suite in mock mode:

```powershell
cd backend
pytest -q
```

Run live OneMap integration tests only with both credentials and an explicit flag:

```powershell
$env:RUN_ONEMAP_INTEGRATION = "true"
$env:ONEMAP_MOCK = "false"
pytest -m integration -q
```

Run the separately gated LLM integration test only with an API key and explicit flag:

```powershell
$env:RUN_LLM_INTEGRATION = "true"
pytest -m llm_integration -q
```

Frontend checks:

```powershell
cd frontend
npm run build
npm run lint
npm run test:e2e
```

Credential and combined-deployment checks:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\scan_secrets.py
.\.venv\Scripts\python.exe scripts\deployment_smoke.py --frontend-dir ..\frontend\out
```

## Private-beta deployment

The root `Dockerfile` builds the static Next.js export and serves it with FastAPI from the same HTTPS origin. `render.yaml` provisions one Docker web service in Singapore with a 1 GB persistent disk at `/data`; SQLite remains intentionally single-instance for this small beta. Only the operator must connect a private Git repository to Render and enter the server-side OneMap secrets. Full publish, retention and backup steps are in [docs/private-beta-operations.md](docs/private-beta-operations.md).

## Known limitations after V0.7.2

See [docs/architecture.md](docs/architecture.md), [docs/v072-manual-qa.md](docs/v072-manual-qa.md), [docs/onemap-pt-contract.md](docs/onemap-pt-contract.md), [docs/v05-data-and-benchmarks.md](docs/v05-data-and-benchmarks.md), and [docs/v06-intent-evaluation.md](docs/v06-intent-evaluation.md). Location context is deterministic and may be an area/station fallback rather than a verified entrance; reverse geocoding was not added to the already bounded optimisation request. Opening hours are sparse and unknown hours are never presented as open. The grammar and catalog remain bounded, indoor routing is unavailable, live OneMap latency varies, SQLite is single-instance, and external navigation accuracy is outside the app’s control.
