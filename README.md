# Along

**Journey-aware errand planning for Singapore public transport.**

Along finds places to complete one or two errands without turning an existing trip into a large detour. Instead of searching only for the nearest shop, it compares candidate stops against the direct public-transport journey and ranks them by added time, walking and transfers.

> **Status:** active development. This repository is a curated public portfolio snapshot; the hosted beta and bulky development datasets/fixtures are not public yet.

## Why I built it

A normal maps search can tell you where a shop is, but not whether stopping there makes sense **on the way** from A to B.

Along treats the direct journey as the baseline, then asks a different question: which real stop satisfies the errand with the least additional inconvenience?

For example:

```text
From: Punggol MRT
To: Orchard MRT
Need: groceries + pharmacy
```

The request is evaluated as a routing problem rather than a nearest-place lookup.

```mermaid
flowchart LR
    A[Origin] --> B[Direct transit baseline]
    B --> C[Candidate errand stops]
    C --> D[Prune + route]
    D --> E[Score added time, walking and transfers]
    E --> F[Best along-the-way option]
```

## What it does

- Resolves Singapore locations from station aliases, local entities and OneMap results.
- Handles one or two errands, including same-hub consolidation when both can be completed at one stop.
- Uses a SQLite/FTS5 POI catalog for local place discovery.
- Supports natural-language needs and preferences such as preferred brands, detour limits and walking tolerance.
- Compares candidate routes against the direct A→B public-transport baseline.
- Ranks recommendations using added journey time, walking, transfers and user preferences.
- Uses bounded candidate generation, corridor pruning, route-call budgets and caching.
- Can optionally expand discovery through TomTom, Geoapify and web evidence when the local catalog is insufficient.
- Keeps routing and place-provider credentials on the backend.

The core optimiser is deterministic. LLM support is optional and limited to interpreting unfamiliar intent/concepts; it does not invent routes or authoritative place results.

## Stack

| Area | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Leaflet |
| Backend | FastAPI, Python, Pydantic, HTTPX |
| Data | SQLite, FTS5, OpenStreetMap-derived POIs, LTA rail gazetteer |
| Routing / geocoding | OneMap provider abstraction with deterministic mock mode |
| Optional discovery | TomTom, Geoapify, Tavily |
| Testing | Pytest, Playwright |

## Architecture

```text
Next.js client
    │
    ▼
FastAPI
    ├── Location resolver ── LTA gazetteer / local entities / OneMap
    ├── Need resolver ────── concepts / SQLite FTS5 / optional live discovery
    ├── Intent parser ────── deterministic parser / optional LLM fallback
    ├── POI repository ───── SQLite hubs and outlets
    ├── Optimiser ────────── candidate generation → pruning → routing → scoring
    └── Analytics ────────── allowlisted anonymous beta events
```

More detail is in [`docs/architecture.md`](docs/architecture.md).

## Optimisation approach

For each request, Along:

1. Resolves the origin and destination.
2. Computes the direct public-transport route as the baseline.
3. Finds hubs or places that can satisfy the requested errands.
4. Uses straight-line geometry and corridor rules to prune poor candidates before making expensive routing calls.
5. Routes the remaining A→stop→B or A→stop1→stop2→B options.
6. Calculates incremental time, walking and transfers relative to the direct journey.
7. Applies hard requirements and preference-aware scoring.
8. Returns the least disruptive recommendation plus useful alternatives.

For two errands, the optimiser evaluates consolidated stops and both travel orders where separate stops are required.

## Public source map

The files kept public are the parts most useful for technical review:

```text
backend/app/
  config.py                 typed runtime configuration
  db.py                     SQLite/FTS5 repository and taxonomy
  domain.py                 routing and candidate domain models
  providers/                OneMap, mock, LLM and discovery adapters
  services/
    candidates.py           staged candidate generation and pruning
    optimizer.py            routing, caching, scoring and ranking
    intent_optimizer.py     intent → optimisation preferences
    open_needs.py           conservative open-world need parsing
frontend/app/
  page.tsx                  planner workflow
  components/               location, discovery, map and result UI
docs/
  architecture.md           system design and engineering decisions
  onemap-pt-contract.md     live routing-contract validation
  privacy.md                beta analytics/privacy boundary
```

The full development workspace also contains a large OSM capture, generated SQLite databases, sanitized provider regression fixtures, browser artefacts and additional QA tooling. Those are intentionally excluded from this portfolio snapshot rather than committed as repository noise.

## Validation

Before publication, the cleaned full working snapshot passed:

- **188 backend tests**
- **4 credential-gated integration tests skipped by default**
- repository credential scan with no tracked secret values found

The full snapshot includes deterministic unit/regression coverage plus opt-in live provider tests. Frontend dependencies could not be freshly reinstalled in the publication environment, so I am not claiming a new frontend build result for this public snapshot.

## Security and privacy

- `.env`, frontend environment overrides, local databases, virtual environments, build output and test artefacts are ignored by Git.
- Provider credentials remain backend-only.
- OneMap authentication tokens are cached in backend memory rather than exposed to the browser.
- Beta analytics accept an allowlisted schema and do not accept exact coordinates or free-form journey text.
- Live-provider fixtures used during development are sanitized before retention.

## Data

The development build uses a Singapore OpenStreetMap-derived POI capture with source metadata and ODbL attribution. The large raw capture is not committed to this portfolio repository. The repository layer also contains a small curated seed catalog for deterministic development paths.

See [`backend/data/README.md`](backend/data/README.md) for the data/licensing boundary.

## Current limitations

- Singapore only.
- No public hosted demo yet.
- Real routing quality and availability depend on OneMap.
- Place coverage is a snapshot rather than a live business directory.
- No turn-by-turn navigation; selected stops hand off to an external navigation app.
- The project is designed for personal/beta-scale use rather than high-traffic production infrastructure.

## Development history

Along has been built iteratively from baseline routing through multi-stop optimisation, POI discovery, intent parsing and open-world place discovery. A concise release history is kept in [`CHANGELOG.md`](CHANGELOG.md).
