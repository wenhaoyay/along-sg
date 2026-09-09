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

V0.7.1 broadens the ingestion taxonomy without inventing coverage. Additional
everyday-errand mappings remain available for future bounded captures, but a capture
never claims a category with no matching data.

V0.7.6 widens the capture to bus stops and fixes a transform defect that discarded
every way and relation. Overpass honours only the last geometry modifier, so
`out center tags bb` returned `bounds` and no `center`; the transform read only
`center` and dropped 767 elements, among them 244 of the 250 mall polygons - a mall is
mapped as a building outline, not a point. The bundled 2026-08-26 capture therefore
ingested 17 malls and 132 transport nodes, all of them rail.

Reingesting the 2026-09-09 capture produces:

| | before | after |
| --- | --- | --- |
| outlets | 6,199 | 14,777 |
| populated categories | 18 | 27 |
| malls | 17 | 252 |
| transport nodes | 132 | 5,978 |
| hubs beyond 1,200 m of any transport node | 45.6% | 0.2% |

Bus stops are transport nodes only. `station_area` still requires rail within 150 m,
because a bus stop is not a station and Singapore has roughly 5,100 of them against
about 130 rail stations - classifying the two alike would relabel most of the catalog.

Opening hours remain the weakest field: 3,000 of 14,774 active outlets (20%) publish
them. That is twice the previous absolute count and the same proportion. Everything
else is unknown and is presented as unknown.
