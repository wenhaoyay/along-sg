# V0.7.3 Singapore discovery intelligence

## Runtime design

Discovery is a typed layer before routing. `LocationResolver` handles journey endpoints; `NeedResolver` handles errands. Neither optimizer nor frontend reads upstream provider fields.

Location order is exact official entity/code, normalized alias, conservative official fuzzy match, local hub/building, OneMap, then unresolved. Results carry canonical display text, type, coordinates, source, confidence and matched context internally. Only consumer-safe fields are serialized. A low-confidence tie becomes `ambiguous`; it is never silently routed.

Need order is canonical catalog/brand, structured concept vocabulary, SQLite FTS5 over real POI evidence, optional live fallback, then clarification. Semantic types are `brand`, `specific_business`, `category`, `cuisine`, `dish`, `product`, `service`, `place_type`, and `unknown`. The concept file stores aliases, parent category, related search terms and supporting OSM tags. It interprets language; it never asserts an invented shop or menu.

Live and local results normalize to `ResolvedPlace`. Name plus 120-metre proximity controls cross-source duplicates while provenance is retained internally. A confirmed live result becomes an in-memory transient optimizer hub; proprietary provider data is not inserted into SQLite.

## Official Singapore rail data

The committed gazetteer is deterministically built by `backend/tools/build_transit_gazetteer.py` from two official LTA DataMall datasets:

- [Train Station, March 2026](https://datamall.lta.gov.sg/content/datamall/en/static-data.html): station point geometry.
- [Train Station Codes and Chinese Names, January 2025](https://datamall.lta.gov.sg/content/datamall/en/static-data.html): station codes and lines.

The normalized result has 200 unique physical station names, 213 source code rows and 1,235 exact/normalized aliases. Geometry is converted from SVY21 (EPSG:3414) to WGS84 during the build. Raw downloads remain ignored; the normalized JSON includes publisher, dataset editions, URLs, licence and generation date.

`BP9`, `bp 9`, `Bangkit`, `Bangkit LRT`, and `bangkitlrt` all resolve locally to `Bangkit LRT Station` with BP9 context. `CCK`, `Chua Chu Kang`, `Chuachukang`, `NS4`, and `BP1` resolve to Choa Chu Kang. These cases do not call OneMap.

## OSM discovery audit and index

The bundled 26 August 2026 Singapore Overpass capture contains 7,147 elements. Discovery-useful tag coverage is:

| Field | Elements |
|---|---:|
| `name` | 5,857 |
| `brand` | 3,216 |
| `cuisine` | 2,053 |
| `shop` | 1,989 |
| `amenity` | 4,971 |
| any `addr:*` | 3,709 |
| alternate-name field | 1,537 |
| level/unit/indoor mall context | 3,212 |
| `opening_hours` | 1,519 |

Earlier ingestion discarded most of this evidence. V0.7.3 preserves original/alternate names, cuisine, shop, amenity and bounded address/operator metadata. SQLite FTS5 indexes those fields with brand aliases, categories, hub and address. Independent businesses remain searchable with a null canonical brand. The query still captures only stage-relevant POI types; it does not blindly import every OSM object.

## Optional provider decision

OneMap remains the authoritative geocoder/router but its official API documents address/building search, not a comprehensive current-business text-search product. A `LivePlaceSearchProvider` abstraction therefore isolates optional current-place discovery.

| Provider | Current assessment for private beta |
|---|---|
| TomTom Search | Selected optional adapter. Singapore POI fuzzy search, address/coordinates, country restriction, bounded HTTP contract. [Official pricing](https://docs.tomtom.com/pricing) states no credit card is needed; the Search API endpoint used here currently lists 2,500 free requests/month (TomTom's newer Places products have separate quotas). |
| Google Places | Potentially stronger coverage, but [billing must be enabled](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing). [Storage and attribution policy](https://developers.google.com/maps/documentation/places/web-service/policies) is restrictive. Not a default and not implemented. |
| Foursquare | Viable POI product, but its [announced June 2026 pricing](https://docs.foursquare.com/developer/reference/upcoming-changes) has a small 500-call Pro free allowance before paid usage. Not selected. |
| OneMap | Retained for Singapore location entities and routing. [Official documentation](https://www.onemap.gov.sg/apidocs/) does not establish the needed current-business discovery contract. |

No TomTom credential was available during implementation, so no live relevance benchmark is claimed. Contract research and a deterministic mock-provider benchmark were performed. The adapter is disabled unless both `DISCOVERY_LIVE_ENABLED=true` and a backend-only key exist. Google is not called.

Exact proprietary caching rights can depend on the customer agreement. Along therefore uses only a conservative short-lived (default 300 seconds), process-memory cache and does not persist provider payloads. Attribution/usage terms must be reviewed before any public launch.

## Budgets, failures and privacy

Each need resolution performs at most one live search. A two-errand discovery therefore stays below the configured discovery hard budget independently of the optimizer's OneMap routing budget. Calls, cache hits and latency are separate counters. Timeouts, auth/rate-limit/5xx/invalid responses become a bounded provider error; useful local matches remain available.

Catalog-gap telemetry is disabled by default. If an operator explicitly enables `DISCOVERY_GAP_TELEMETRY_ENABLED` and configures the existing admin token, only normalized unresolved need terms and aggregate counts are held in process memory. No journey, coordinates, IP address or raw history is stored. `/api/admin/discovery-gaps` is hidden otherwise.

## Curated evaluation

`backend/data/discovery-evaluation.json` contains 53 location/brand/dish/product/service behavior cases. The latest local run passed all 53 expected classifications/entities, with zero wrong high-confidence resolutions, 18.9% unresolved outcomes (valid semantic classifications without evidenced places), 13.2% ambiguity, 22.6% live-fallback triggers, 21.16 ms mean and 28.71 ms P95 on this workstation. Exact official resolution was 11.3% of the mixed corpus and conservative fuzzy official resolution was 1.9%. The mock live-provider request count was 12 because it intentionally records every low-confidence trigger, including empty mock responses. These rates describe the curated corpus only and are not universal real-world accuracy.

Key acceptance observations:

- Bangkit variants: authoritative exact BP9 result, zero live/OneMap dependency.
- Molly Tea: absent reliable local match triggers the mock live adapter and returns a normalized real-place-shaped candidate; actual TomTom coverage remains unverified without credentials.
- Mee pok/meepok/bak chor mee: classified as `dish`; FTS returns only POIs with name/cuisine/metadata evidence and the UI says “matching places” rather than guaranteeing a menu.
- “I like cats”: remains unresolved and does not trigger a live call.

## Known limits

Bus interchanges and neighborhood aliases are still primarily resolved through local OSM/OneMap rather than a second official gazetteer. OSM coverage and tags are incomplete; a concept can be understood while no evidenced place is found. Live relevance and licensing must be revalidated with a real key before public use. This stage does not add menu data, realtime opening verification, global POIs, LLM place invention or new optimizer scoring semantics.
