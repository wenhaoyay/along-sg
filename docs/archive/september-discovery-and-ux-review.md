# Discovery and journey UX review — 6 September 2026

This review continues V0.7.4 and refines its existing map-first interface.

## Changes

- Balanced / Faster / Less walking controls map to existing optimizer preference weights. Balanced preserves preferences extracted from the request; other choices override only their relevant preference.
- Reverse journey swaps resolved endpoints. Inputs are locked while a request is pending to prevent mismatched results.
- Progress text reflects discovery versus optimization; elapsed time alone no longer claims that transit routing has begun.
- Green typographic emphasis, segmented controls, quieter helper copy, and reduced-motion support preserve the established interface.
- Phrase-boundary matching rejects matches such as Malan Road for mala. Provider category aliases improve compatibility with existing service categories.
- Off-route local matches no longer suppress live discovery. Corridor distance is measured against route segments.
- TomTom along-route 403 can fall back to fuzzy search within its request budget. Other authentication, timeout and rate-limit failures do not trigger this fallback.
- Geographic shortlisting preserves up to two candidates for a need that would otherwise disappear entirely. Existing detour and routing budgets still apply.
- Web grounding rejects generic lead names and one-word location hints. Named-business location grounding requires explicit business evidence; dishes cannot be renamed from a geocoded location.
- HTTP request INFO logging is suppressed because provider URL query parameters contain credentials. The source/bundle secret scan now includes all three discovery-provider keys.

## Live evidence

OneMap authentication and routing succeeded. TomTom fuzzy search, Geoapify geocoding and Tavily search returned responses. TomTom along-route returned 403 with the configured key while fuzzy search succeeded; the precise account entitlement was not established.

Senja LRT → Orchard MRT, requested departure **2026-09-06 21:47 Singapore time**:

| Case | Baseline | Total incl. dwell | Extra time | Walk | Transfers | Routing calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Molly Tea, Orchard Central (181 Orchard Road) | 38.45 min | 62.14 min | 23.69 min | 1,204.8 m | 2, no extra | 3 incl. baseline |
| Jalan Tua Kong Mee Pok + Guardian, ION Orchard | 38.45 min | 70.76 min | 32.31 min | 1,378.9 m | 2, no extra | 6, baseline cached |

The two-errand case previously generated zero candidates. After preserving category coverage it generated six candidates, shortlisted one stop combination and evaluated both visit orders. Optimization latency was 1.07 seconds for Molly Tea and 2.77 seconds for the compound case, excluding discovery and the initial baseline request. Discovery in this final diagnostic used 16 TomTom, 6 Geoapify and 3 Tavily requests. Both scenarios stayed below the 12-route bound. Two such diagnostic runs were made on September 6 (50 discovery requests total); the separately gated OneMap suite also ran.

These results verify routing feasibility, not whether businesses were open at the late departure time. Opening hours, queue time and Panadol stock were not verified. Molly Tea coordinates are grounded to its mall, not a verified storefront entrance. A usable transit route is not sufficient evidence that a stop can be completed at that hour.

## Verification and remaining acceptance work

- Full backend regression: 189 passed, 4 explicitly gated tests skipped; the focused discovery suite also passed 21 tests.
- Gated OneMap integration: 3 passed.
- Frontend ESLint, TypeScript and production build passed.
- Playwright: 22 passed across mobile and desktop, including visual captures, route reversal and preference submission. Screenshots use mocked APIs and blank map tiles; they do not verify live basemap delivery.
- Source/bundle secret scan passed. Root `.env` remains ignored and untracked.

The earlier 52-query utility uses an **automated lexical rubric**, not human relevance labels. Its percentages must not be presented as completed manual acceptance. Earlier evaluations also used differing catalogs and synthetic two-point corridors, so comparison to the historical 59.6% zero-result rate is not a controlled estimate. Historical total API usage cannot be reconstructed exactly: one earlier run lost its report during SQLite cleanup. Do not use the earlier speculative call totals.

Full product acceptance remains open: a fixed-catalog corpus, independent candidate/address review, opening-hour handling, fuller failure/budget tests and fresh final-code relevance evaluation are still needed. Live reports remain in ignored `work/`; no credentials or raw request headers are recorded in those reports. No deployment or merge was performed.

## Credential incident

On August 30 the existing HTTP client INFO logger printed TomTom and Geoapify credential-bearing URLs into tool output. This cannot be undone by changing source code. Those two keys should be revoked/replaced if they have not already been rotated. No claim is made that rotation has been verified. Raw URL logging is now disabled and scanning covers these keys.
