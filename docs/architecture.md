# Architecture

## System boundary

```text
Next.js browser
    │ JSON over /api/*
    ▼
FastAPI
    ├── LocationResolver
    │   └── LTA rail gazetteer → local entities → OneMap fallback
    ├── NeedResolver
    │   └── concepts → SQLite FTS5 → optional live discovery
    ├── IntentParserService
    │   ├── deterministic parser
    │   └── optional structured LLM adapter
    ├── MapProvider
    │   ├── MockOneMapProvider
    │   └── OneMapProvider
    ├── HubRepository
    │   └── SQLite hubs, outlets and discovery metadata
    ├── Optimizer
    │   └── candidates → pruning → routing → scoring → ranking
    └── AnalyticsRepository
        └── allowlisted anonymous beta events
```

The browser only receives the API base URL. OneMap credentials, provider keys and access tokens stay on the backend.

## Baseline-first optimisation

Along treats the direct A→B public-transport route as the baseline. Candidate recommendations are measured by the inconvenience they add to that journey rather than by distance to the user alone.

For a one-stop errand, the routed comparison is:

```text
A → stop → B
```

For two errands, the optimiser considers:

- one consolidated hub that satisfies both needs;
- two separate stops in both possible orders.

Before routing, a Haversine detour proxy and corridor rules remove obviously poor candidates. Only the remaining candidates consume route-provider calls.

## Scoring

The central score combines incremental journey cost:

```text
overall = added duration × detour weight
        + added walking × walking weight
        + added transfers × transfer weight
```

Preferences such as a preferred brand or same-stop consolidation can adjust ranking. Explicit requirements and user-specified hard limits are handled separately from soft preferences.

Incremental values are clamped at zero relative to the baseline so provider-estimation noise cannot create a negative inconvenience reward.

## Location resolution

The client does not send arbitrary location text directly into optimisation. Location input is resolved first and the selected result carries a confirmed display value and coordinates.

Resolution uses:

1. the local Singapore rail gazetteer and station aliases;
2. local entities/hubs;
3. OneMap fallback where configured.

This keeps provider-specific identifiers out of the consumer API.

## Need and place discovery

The static catalog is backed by SQLite and FTS5 over Singapore POI data. Known categories and brands are deterministic.

Unknown but plausible needs can enter the open-world discovery path. Live providers are optional and bounded by call budgets. Web evidence can identify a candidate business, but a result must be grounded to real coordinates before it can participate in route optimisation.

The optional LLM adapter is limited to intent/concept interpretation. It does not authoritatively create businesses or routes.

## OneMap provider boundary

`MapProvider` exposes stable geocoding and public-transport routing methods so the optimiser is isolated from OneMap response details.

`OneMapTokenManager` caches access tokens in backend memory and serializes refreshes. The OneMap adapter normalizes upstream responses before they reach the rest of the application. Mock mode implements the same contract for deterministic local tests.

Live-provider tests are explicitly opt-in because availability and response contracts are external dependencies.

## Data model

SQLite stores physical hubs and their outlets separately. A hub can therefore satisfy multiple categories without routing independently to every shop inside the same mall or interchange.

The repository also maintains searchable discovery metadata and local reference data. Generated runtime databases are ignored from Git and can be rebuilt from the bundled public data.

## Privacy and analytics

Beta analytics accept a fixed allowlist of event fields rather than arbitrary client payloads. Exact coordinates and free-form user text are not accepted by the analytics endpoint.

See [`privacy.md`](privacy.md) for the current beta boundary.

## Failure behavior

- Input validation errors return 422.
- Provider/normalization failures are translated to API errors without forwarding credentials or raw upstream bodies.
- Candidate and route-call budgets bound external work.
- Required errands are not silently dropped.
- When no convenient option exists, the response distinguishes fallback/closest results from a normal recommendation.

## Deployment scope

The repository includes a single-container deployment configuration that can serve the FastAPI API and a static frontend export. The current project is intended for personal/beta-scale use, not as a high-traffic production service.
