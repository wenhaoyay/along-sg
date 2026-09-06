# Along

**Journey-aware errand planning for Singapore public transport.**

Along finds places to complete one or two errands without turning an existing trip into a large detour. Instead of searching only for the nearest shop, it compares candidate stops against the direct public-transport journey and ranks them by added time, walking and transfers.

> **Status:** active development. The hosted beta is not public yet.

![Along route recommendation](docs/assets/along-route-result.png)

## Why I built it

A normal maps search can tell you where a shop is, but not whether stopping there makes sense **on the way** from A to B.

Along treats the direct journey as the baseline, then asks a different question: which real stop satisfies the errand with the least additional inconvenience?

For example, a request such as:

```text
From: Punggol MRT
To: Orchard MRT
Need: groceries + pharmacy
```

is evaluated as a routing problem rather than a nearest-place lookup.

## What it does

- Resolves Singapore locations from station aliases, local entities and OneMap results.
- Handles one or two errands, including same-hub consolidation when both can be completed at one stop.
- Searches a local SQLite/FTS5 POI catalog built from Singapore OpenStreetMap data.
- Supports natural-language needs and preferences such as preferred brands, detour limits and walking tolerance.
- Compares candidate routes against the direct A→B public-transport baseline.
- Ranks recommendations using added journey time, walking, transfers and user preferences.
- Uses bounded candidate generation and route-call budgets to keep optimisation practical.
- Can optionally expand discovery through TomTom, Geoapify and web evidence when the local catalog is insufficient.
- Keeps routing and place-provider credentials on the backend.

The core optimiser is deterministic. LLM support is optional and limited to interpreting unfamiliar intent/concepts; it does not invent routes or authoritative place results.

## Stack

| Area | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Leaflet |
| Backend | FastAPI, Python, Pydantic, HTTPX |
| Data | SQLite, FTS5, OpenStreetMap POIs, LTA rail gazetteer |
| Routing / geocoding | OneMap provider abstraction with deterministic mock mode |
| Optional discovery | TomTom, Geoapify, Tavily |
| Testing | Pytest, Playwright |
| Deployment | Docker / Render configuration |

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

## Repository layout

```text
backend/
  app/              API, providers, discovery, data access and optimiser
  data/             public Singapore reference data and evaluation corpora
  fixtures/         sanitised routing fixtures
  scripts/          ingestion, diagnostics and operational helpers
  tests/            deterministic and opt-in integration tests
  tools/            discovery evaluation and data-building utilities
frontend/
  app/              Next.js application
  e2e/              Playwright browser tests
docs/
  architecture.md   current design and engineering decisions
  privacy.md        beta analytics/privacy boundary
```

## Run locally

### 1. Backend

Python 3.12+ is recommended.

```bash
cp .env.example .env
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Mock routing is enabled by default, so the project can be explored without external credentials.

### 2. Frontend

Node.js 20.9+ is required.

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`.

## Tests

Backend:

```bash
cd backend
pytest -q
```

The current portfolio snapshot passes **188 backend tests**, with four credential-gated integration tests skipped by default.

Frontend:

```bash
cd frontend
npm run lint
npm run build
npm run test:e2e
```

Live OneMap and LLM integration tests are opt-in so the default suite remains deterministic and credential-free.

## Configuration and secrets

Copy `.env.example` to `.env` for local development. `.env`, frontend environment overrides, local databases, build output, virtual environments and test artifacts are ignored by Git.

Provider keys are backend-only. Do not place OneMap credentials or private provider keys in `NEXT_PUBLIC_*` variables.

A source scan is also included:

```bash
python backend/scripts/scan_secrets.py
```

## Data

The bundled Singapore POI capture is derived from OpenStreetMap and includes source metadata and attribution. See [`backend/data/README.md`](backend/data/README.md) for ingestion and licensing notes.

## Current limitations

- Singapore only.
- No public hosted demo yet.
- Real routing quality and availability depend on OneMap.
- The bundled POI snapshot is not a live business directory.
- No turn-by-turn navigation; selected stops hand off to an external navigation app.
- The project is designed for personal/beta-scale use rather than high-traffic production infrastructure.

## Development history

The project has been built iteratively from baseline routing through multi-stop optimisation, POI discovery, intent parsing and open-world place discovery. A concise release history is kept in [`CHANGELOG.md`](CHANGELOG.md).
