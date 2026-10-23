# V0.5 POI data and optimisation benchmarks

## Source and licence

The V0.5 import uses a Singapore-only Overpass query over OpenStreetMap. The captured
export is `backend/data/singapore-osm-pois.json`; it records the exact query, capture time,
endpoint and attribution in `capture_metadata`. Data © OpenStreetMap contributors,
licensed under ODbL 1.0. No paid POI provider is required.

Capture timestamp: 2026-08-26T12:16:53.644783+00:00.

The raw response contained 7,147 elements and 6,242 category-relevant POIs. Import
produced 6,162 OSM POIs after removing 80 deterministic duplicates. Combined with the
curated fallback, SQLite contains 6,192 outlets, 6,191 active outlets, 6,138 hubs, 15
malls and 132 transport nodes. SQLite lookup and pruning remained in tens of milliseconds,
so there is no measured reason to introduce PostGIS.

## Normalisation and coverage

The deterministic taxonomy covers fast food, fried chicken, bubble tea, coffee,
supermarket, pharmacy, convenience store, ATM/banking, electronics and parcel collection.
Parent/child category relationships are stored in SQLite and descendant categories satisfy
parent searches.

Known alias rules canonicalised 2,169 OSM records to 21 brands. Examples include KFC,
Jollibee, FairPrice, Cold Storage, Guardian, Watsons, 7-Eleven, Cheers, Starbucks, LiHO,
KOI Thé, DBS/POSB, OCBC, UOB and SingPost. Source element IDs remain on each outlet.

Opening hours are present for 1,382 of 6,162 OSM POIs (22.4%). Missing hours remain null.
All imported POIs carry the source capture timestamp as freshness metadata. One clearly
closed record is retained with `closure_status=closed` and excluded from candidates.

Mall containment uses OSM way bounds where available and a conservative 75 metre centre
fallback. Standalone POIs remain separate hubs. Every hub records nearest transport-node
association and distance when available. The curated ten hubs remain as reviewed coverage
for major malls and station areas underrepresented by OSM mall tagging.

## Candidate pipeline

The measured stages are:

1. active raw POIs;
2. category-matching hubs;
3. baseline encoded-polyline corridor plus origin/destination radii;
4. transit-node proximity;
5. hub coverage and same-hub consolidation;
6. approximate Haversine detour;
7. conservative route-budget admission;
8. live OneMap routing and maximum-reasonable-detour validation.

The final admission gate estimates two calls for a one-stop option and six calls for both
orders of a separate two-stop option. It chooses a complete evaluable subset within the
hard budget instead of starting work that will be truncated.

## Cache strategy

The process-local LRU cache key is the directed start/end coordinate pair rounded to six
decimal places plus a floored one-minute Singapore departure bucket when time-dependent
routing is enabled. Default TTL is five minutes and capacity is 512 entries. Direction and
time remain part of the key; departures two minutes apart are covered by different entries.
The cache never contains credentials or upstream raw payloads.

## Concurrency evaluation

Candidate-level concurrency is implemented with an explicit semaphore and in-flight key
coalescing. The deterministic suite proves a limit of two is obeyed. A live run at
concurrency two reduced the first case from seconds to 742 ms, but OneMap then returned
persistent HTTP 429 responses during the fourth case despite bounded retries. Production
therefore defaults to sequential routing (`OPTIMIZER_ROUTING_CONCURRENCY=1`). The feature
is configurable for future controlled re-evaluation but is not enabled by default.

## Benchmark results

Both reports use six representative one/two-errand Singapore cases and are stored as
`docs/v05-benchmark-mock.json` and `docs/v05-benchmark-live.json`.

Deterministic mock benchmark after route-budget pruning:

- average route calls: 8.0; worst: 9;
- cache-hit rate: 7.69%;
- P50/P95 total latency: 40.64/48.88 ms;
- hard budget reached: never.

Sequential live OneMap benchmark:

- average route calls: 8.0; worst: 9;
- cache-hit rate: 7.69%;
- P50/P95 total latency: 1,255.55/2,096.15 ms;
- average summed provider latency: 774.17 ms;
- hard budget reached: never.

The final sequential sample met the aspirational <3 s median and <6 s P95 goals. A prior
sequential sample from the same day measured 6,744.99/12,847.87 ms, showing substantial
upstream variability; six cases are not enough to treat either distribution as a service
guarantee. Unsafe request concurrency is not used to conceal that limitation.

## Representative live recommendations

- Punggol–Orchard, fried chicken: KFC near the corridor; 19.31 minutes added including
  the configured 15-minute dwell.
- Jurong East–Bugis, coffee: Starbucks near the origin; 15.81 minutes added including
  12-minute dwell.
- Tampines–Orchard, bubble tea: R&B巡茶 near Tampines; 9.36 minutes added including
  8-minute dwell.
- Punggol–Orchard, groceries + pharmacy: consolidated at ION Orchard; 29.87 minutes
  added, approximately the configured 30-minute combined dwell.
- Jurong East–Tampines, convenience + ATM: 7-Eleven and UOB near journey endpoints;
  38.37 minutes added including 20 minutes dwell.
- Bugis–VivoCity, electronics + coffee: VivoCity and a nearby café; 28.94 minutes added
  including 27 minutes dwell.

These are diagnostic observations, not guarantees of business availability. Unknown or
stale opening hours must be verified before travel.
