# V0.7.4 open-world Singapore discovery

Status: implementation branch only. Do not deploy or merge before product-owner acceptance.

## Why the boundary changed

V0.7.3 could resolve only terms represented by a known concept, catalog category or high-confidence place. V0.7.4 makes a plausible errand valid before taxonomy resolution. `OpenNeed` preserves the raw and normalized phrase, inferred semantic type, optional known concept, brand/category/product/dish/service hints, brand hardness, optionality, substitution policy, confidence, resolution status, search terms, likely place types and evidence requirements.

The deterministic parser rejects conversational non-errands such as “I like cats” and “tell me a joke”, but accepts intent verbs and short commodity/food/service/place searches. It splits at most two independent clauses. Each clause is resolved independently; a failure cannot erase a successful sibling need.

Open needs receive request-scoped categories such as `open_mee_pok`. Those categories never query every restaurant or shop in SQLite. Only transient, coordinate-bearing places whose evidence supports that exact need are inserted into candidate generation. This is the main wrong-result guard.

## Provider ladder and budgets

The ladder is deliberately sequential:

1. SQLite FTS5 over curated and attributed OSM data.
2. Deterministic Singapore aliases and general lexical expansion.
3. At most one optional structured LLM expansion for an unknown plausible term.
4. Primary live place search, at most two calls per need.
5. Secondary live place search, at most one call per need when the primary is empty, weak or failed.
6. Optional web search, at most one call per need.
7. Ground at most four web candidates through local/place/geocoding sources.
8. Rank/deduplicate evidence and pass only a bounded top set into the existing optimiser.

Provider failures return the useful results already accumulated. Authentication and ordinary 4xx failures are not retried. Timeouts, rate limits and upstream 5xx responses receive at most one exponential-backoff retry by default. The live adapters use a five-minute, 64-entry process-local LRU; proprietary payloads are never written to SQLite. Routing retains its existing 10-call soft and 12-call hard budgets.

The optimiser now computes/reuses its baseline route before transient place discovery. Normalized leg geometry becomes the search corridor and also seeds the route cache, so corridor construction does not cause a duplicate baseline route call.

## Current providers (official terms checked 2026-08-30)

### TomTom primary

The adapter uses Search API v2 fuzzy search, Singapore restriction, point/radius bias, and the along-route endpoint when normalized route geometry exists. Timeouts, retries, source normalization and backend-only credentials are bounded. TomTom's [official pricing page](https://docs.tomtom.com/pricing) lists 2,500 free Search API requests per month and says no credit card is needed to start. That page now labels this Search API as the previous-generation map format; migration to Orbis Places Search must be reviewed before the legacy service's published decommissioning. No TomTom key was configured during this implementation, so the adapter is contract-tested but no live relevance claim is made.

TomTom results remain ephemeral for five minutes. The team must re-check the applicable product terms before changing storage duration or persisting results.

### Geoapify secondary

Geoapify was selected as the second place source. The adapter uses the official free-text Geocoding API with `filter=countrycode:sg` plus corridor proximity bias. Geoapify documents [3,000 free credits per day with no credit card](https://www.geoapify.com/pricing/) and up to five requests/second on the free plan. Its [Places documentation](https://apidocs.geoapify.com/docs/places/) supports named category searches within circles, rectangles and place boundaries. The free plan requires Geoapify and OpenStreetMap attribution. Geoapify states that results may be cached/stored/reused with the required attribution; Along nevertheless keeps live results ephemeral so both providers share one conservative policy. No Geoapify key was configured, so only request/response contract tests ran.

### Tavily web evidence

Tavily is the optional default `WebDiscoveryProvider`. Its [official pricing documentation](https://docs.tavily.com/documentation/api-credits) lists 1,000 credits per month without a credit card; a basic search costs one credit. The adapter requests short result metadata only—no generated answer or raw page content.

Exa was also reviewed. Its [official API pricing](https://exa.ai/pricing?tab=api) currently offers $20 at signup plus $10 monthly without a payment method and prices basic Search at $7 per 1,000 requests. Brave's current API plan includes monthly credits but its official API privacy notice says payment information is required. Tavily was chosen for this stage because the basic-search credit contract, compact result structure and no-card monthly allowance fit a strictly optional one-search fallback. No web-search key was configured, so no live web result is claimed.

## Evidence and grounding

`CandidatePlaceEvidence` records source, source type, tier, direct-name match, category match, item/dish match, address/coordinate agreement, source count and bounded observed text. Tiers are `VERIFIED`, `STRONG`, `SUPPORTED` and `WEAK`. Cross-source deduplication uses normalized name, address and a 150-metre coordinate threshold while retaining provenance.

Web pages can identify candidate business names only. A web result cannot become a `ResolvedPlace`; it must match a local record or a coordinate-bearing place/geocoding provider result. Ungrounded candidates are discarded.

Dish searches require direct dish/name/menu/tag evidence. A generic Chinese or noodle restaurant is not treated as a mee-pok seller. Product searches may use a relevant business category, but the suitability remains `category_likely`. Consumer wording is “Pharmacies for Panadol” or “Stock not guaranteed”, never an inventory claim. `inventory_verified` exists in the normalized model but this stage has no inventory provider and does not emit it.

## Optional semantic LLM

`OpenAISemanticExpansionProvider` is disabled by default. It receives only one plausible unknown need, returns strict structured type/canonical/generic/search-place terms, uses `store=false`, has no tools, and is instructed not to name businesses, outlets, coordinates, stock, routes or hours. Deterministic concepts such as KFC, BP9, pharmacy and coffee bypass it. Metrics track calls, latency and provider-supplied token counts; cost remains unknown unless supplied rather than being guessed from a hard-coded price table.

## Privacy and failure semantics

Provider calls include only the need term and the minimum bounded geographic context needed for relevance. Route endpoints are represented by a corridor/centre; identity and account data are never sent. Raw queries are not added to persistent analytics. Optional in-process gap counts remain disabled by default.

Only after local, semantic and all enabled live/web stages fail does the API say: “We couldn't find a reliable place for 'X'.” A compound request preserves successful needs and reports the missing term. Missing keys disable their providers; deterministic local development and tests remain fully offline.

## Evaluation

`backend/data/open-world-evaluation.json` declares 272 cases: 240 templated food/product/service/business requests, 10 colloquial requests, 10 compounds and 12 non-errands. The templates deliberately test language variation without becoming production concept mappings. Run:

```powershell
cd backend
.\.venv\Scripts\python.exe tools\evaluate_open_world_discovery.py
```

The default evaluator ingests the bundled attributed Singapore OSM snapshot, disables all network providers and reports acceptance, false-nonsense acceptance, local grounded resolution, zero-result, wrong semantic type, compound completeness and latency. Offline zero results are expected for inventory/menu terms absent from the snapshot; they must not be hidden with weak generic businesses.

The final V0.7.4 offline run covered 272 queries. Plausible-need acceptance was 100%, false-nonsense acceptance was 0%, local grounded resolution was 40.4%, and the local-only zero-result rate was 59.6%. Compatible semantic-type classification was correct for all labelled cases. Compound parsing was complete for 100%; 80% had one locally resolved clause and 10% had both clauses locally resolved. The remaining compound case had no grounded local clause. Mean parser latency was 0.35 ms and P95 was 0.32 ms on the development machine. Network-provider calls and routing calls were both zero. A place-level wrong-result rate is deliberately not inferred from this concept corpus: that requires a separately human-labelled place-relevance set. Weak or unsupported places are filtered before routing.

When live place keys are available, run the bounded comparison matrix (ten documented Singapore queries, at most five returned hits each):

```powershell
cd backend
.\.venv\Scripts\python.exe tools\compare_live_discovery.py --output ..\work\live-discovery-comparison.json
```

The output contains names, addresses, coordinates, categories and latency, but never provider keys. With neither key configured, the tool exits successfully with an explicit `not_run` status.

## Known limitations

- No configured TomTom, Geoapify, Tavily or OpenAI key was available during V0.7.4 implementation; live comparison findings must remain “not tested”.
- Generic place APIs usually prove business existence/category, not item stock or menu availability.
- The bundled OSM snapshot is a point-in-time capture and does not contain every Singapore business or dish.
- Along-route TomTom behavior is contract-tested but awaits a live key and should be migrated if TomTom retires Search API v2.
- The lexical classifier is intentionally conservative; ambiguous short nouns may remain `unknown` until an optional semantic provider expands them.
- Partial discovery can continue with resolved errands, but the current one-screen UI does not provide a separate per-term retry control; editing and resubmitting is the retry path.
