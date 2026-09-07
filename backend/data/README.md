# Singapore POI data

`singapore-osm-pois.json` is a Singapore-only OpenStreetMap export captured through the
public Overpass API. Its `capture_metadata` object records the capture time, endpoint,
query, geographic scope, attribution and licence URL.

Data © OpenStreetMap contributors. OpenStreetMap data is available under the Open Data
Commons Open Database License (ODbL) 1.0:
https://www.openstreetmap.org/copyright

The generated SQLite database is a derivative database and is intentionally ignored by
Git. If it is distributed or publicly used, preserve the OSM attribution and comply with
the ODbL share-alike requirements. Rebuild it with:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ingest_osm_pois.py --input data\singapore-osm-pois.json
```

Omitted opening hours mean unknown; they are never inferred. `last_verified_at` records
the source capture time, not a guarantee that an individual business was field-checked
on that date.

V0.7.1 broadens the ingestion taxonomy without inventing coverage. Reingesting the
bundled 2026-08-26 capture produces 6,199 total outlets (6,198 active) across 18
populated categories. Additional everyday-errand mappings remain available for future
bounded captures, but the current capture does not claim categories with no matching data.
