# Official Singapore public-data layers

Along's core recommendation engine remains journey-aware rather than a general-purpose
"everything map". Official datasets are added only when they improve one of two things:

1. **routeable stops** that can be evaluated as an errand or useful stop; or
2. **context layers** that are useful to see around a journey but should not be treated as
   a destination without stronger access evidence.

## Sources

The first public-data expansion uses the following upstream datasets directly from
data.gov.sg. Along does not scrape or depend on a third-party map.

| Key | Agency / dataset | data.gov.sg id | Along treatment |
| --- | --- | --- | --- |
| `mrt_exits` | LTA MRT Station Exit | `d_b39d3a0871985372d7e1637193335da5` | transport nodes + map layer |
| `hawker_centres` | NEA Hawker Centres | `d_4a086da0a5553be1d89383cd90d07ecd` | routeable place + map layer |
| `sport_facilities` | SportSG Sport Facilities | `d_2cfb0867cdeb2b7303068995699dc33b` | context layer only |
| `park_facilities` | NParks Park Facilities | `d_14d807e20158338fd578c2913953516e` | routeable amenities + map layer |
| `parks` | NParks Parks and Nature Reserves | `d_77d7ec97be83d44f61b85454f844382f` | geometry layer |
| `nparks_tracks` | NParks Tracks | `d_306cc1018cb733346681883ee6d73054` | PCN / track geometry layer |

The data.gov.sg download API is used only by the ingestion command. Normal user requests
do not call data.gov.sg.

## Why there are two storage paths

The existing `hubs` / `outlets` model is intentionally a point-destination model. It is
what the optimiser can route to and compare against a direct journey.

Lines and polygons do not fit that contract. A park connector is not one stop and a park
polygon should not silently become an arbitrary centroid. Those records are therefore
kept in `public_geo_features`, preserving the published geometry and properties with a
bounding box for cheap viewport queries.

```text
official dataset
      |
      +-- trustworthy routeable point ----> hubs / outlets ----> optimiser
      |
      +-- point / line / polygon ----------> public_geo_features ----> map context
```

`GET /api/public-layers` exposes the second path as a bounded GeoJSON FeatureCollection.
Callers must provide a bounding box; the response is capped and reports whether it was
truncated.

## Routeability rules

### MRT exits

Each exit is stored as a transport node, not an errand. This gives nearby official places
better transit proximity/context while retaining the existing rail/bus graph.

### Hawker centres

NEA hawker centres are routeable. They receive the `hawker_centres` category and their
published status/address are retained when present.

### NParks facilities

Point facilities are routeable and mapped conservatively from the published `CLASS`:

- fitness / exercise -> `fitness`
- toilet / washroom -> `public_toilets`
- playground -> `playgrounds`
- carpark / parking -> `parking`
- dog run -> `dog_runs`
- every imported point also carries `park_facilities`

Unknown classes stay `park_facilities`; the importer does not invent a more specific
category.

### SportSG facilities

SportSG records are **context-only in this version**. The dataset contains facilities at
venues whose public access is not represented reliably enough for the optimiser to claim
that a traveller can stop there. They are retained with `_along_access=unknown` rather
than discarded or presented as definitely usable.

### Parks and tracks

Parks, park connectors and other tracks remain geometry. No centroid destination is
invented. NParks track records are classified as `park_connectors` only when the source
`TYPE` / `PARK_TYPE` indicates Park Connector / PCN; the rest remain `park_tracks`.

## Ingestion

Download the current official snapshots and build them into the same local SQLite
database used by Along:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ingest_public_data.py
```

Limit the run when developing one parser:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_public_data.py --datasets mrt_exits hawker_centres
```

For reproducible/offline parser work, save or read raw snapshots:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_public_data.py --save-raw-dir data\official
.\.venv\Scripts\python.exe scripts\ingest_public_data.py --input-dir data\official
```

MRT exits are intentionally ingested first when they are part of a run. Routeable public
places are then linked to the nearest currently-known transport node so the existing
candidate pipeline can apply its transit-proximity heuristics.

## Refresh semantics

Each upstream dataset has its own `source` key. Refreshing one official source replaces
only rows belonging to that source. The pre-existing repository behaviour that retires a
matching bootstrap hub is restricted to `curated` seed hubs; one authoritative source is
never allowed to delete another source simply because their normalized display names
match nearby.

## Consumer identity

The SQLite `hubs.name` column is globally unique, so official imported hubs include a
dataset-qualified internal suffix. `presentation.safe_label()` strips that suffix before
anything reaches the UI. Source ids remain available internally for deterministic refresh
and provenance.

## Licensing and attribution

These datasets are obtained from data.gov.sg under the Singapore Open Data Licence.
Retain the required attribution and licence notice when distributing or serving derived
data. OpenStreetMap remains a separate ODbL source with its own attribution and
share-alike requirements; this integration does not change that boundary.
