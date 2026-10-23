# Data sources

Every place, stop and landmark Along shows comes from one of the files below,
all kept in `backend/data/`. Each file records its own source, capture time and
licence. The SQLite catalogue built from them (`errands.db`) is a derivative
database and is not committed.

| File | What it holds | Source | Licence |
| --- | --- | --- | --- |
| `singapore-osm-pois.json` | Shops, food, services, malls, rail stations, bus stops | OpenStreetMap via the Overpass API | ODbL 1.0 |
| `singapore-osm-post-offices.json` | `amenity=post_office` (SingPost counters) | OpenStreetMap via the Overpass API | ODbL 1.0 |
| `singapore-hsa-pharmacies.json` | Registered retail pharmacies, with coordinates | Health Sciences Authority, "Retail pharmacy locations", data.gov.sg dataset `d_bb92615f43de22933e4479558b1f6c36` | Singapore Open Data Licence 1.0 |
| `singapore-transit-gazetteer.json` | MRT/LRT stations and their names | Land Transport Authority DataMall | Singapore Open Data Licence |

## Attribution

- Map data © OpenStreetMap contributors, available under the Open Database
  License: https://www.openstreetmap.org/copyright
- Contains information from Retail pharmacy locations accessed from
  data.gov.sg, which is made available under the terms of the Singapore Open
  Data Licence version 1.0: https://data.gov.sg/open-data-licence
- Contains information from LTA DataMall, made available under the Singapore
  Open Data Licence.

## How the catalogue is built

1. `scripts/ingest_osm_pois.py --input data/singapore-osm-pois.json` reads the
   main capture and merges the supplements beside it
   (`app/poi_ingestion.load_catalogue`). The main capture file is never
   rewritten to add them.
2. Post offices are OSM elements and merge by element id.
3. A registered pharmacy is added only where OSM maps no pharmacy within 80 m;
   otherwise the OSM shop stands for it. Added pharmacies keep their own
   source (`hsa_pharmacy_register`) and the register's last-updated date as
   `last_verified_at`. Coordinates are the register's own (WGS84); nothing is
   geocoded at ingest and OneMap is never called.
4. The catalogue records the capture time and a fingerprint of all the files
   plus the transform version in `catalog_meta`. On deploy,
   `scripts/prepare_beta_data.py` re-ingests whenever that fingerprint differs,
   so a new capture reaches a persistent volume.

Refresh the supplements with `scripts/fetch_supplementary_data.py` (one
Overpass query and two data.gov.sg calls, paced for its rate limit).

## The bootstrap seed

`app/db.py` carries twelve curated malls with illustrative outlets so the app
and its tests run without any capture. They are not verified data
(`last_verified_at` is NULL). Ingesting the full catalogue retires all of them,
for good (`catalog_meta.curated_seed_retired`).
