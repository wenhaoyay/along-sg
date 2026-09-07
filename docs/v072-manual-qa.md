# V0.7.2 consumer-polish QA

Captured 2026-08-29 in deterministic mock mode against the local 6,199-outlet catalog.
The full matrix was exercised through the intent and optimisation API. Cases A and B were
also inspected interactively in the responsive browser UI; desktop and a 390 × 844 mobile
viewport were checked. Playwright separately covers the journey flow, discovery palette,
deduplication, error recovery and mobile rendering.

## Product matrix

| Case | Observed result | Calls | Mock latency |
|---|---|---:|---:|
| A. Boon Lay → Fajar, fried chicken | Best option: KFC, “Near Tengah Plantation · 218 m”, +18.32 min; a differentiated easier alternative was offered | 7 | 64.50 ms |
| B. Boon Lay → Fajar, fried chicken + bubble tea | KFC near Tengah then Koi Cafe at Hillion Mall, +32.15 min; partial (+20.83) and easier (+28.83) alternatives | 7 | 318.62 ms |
| C. Punggol → Orchard, groceries + pharmacy | Consolidated one-stop ION Orchard result, +36.13 min | 10 | 179.55 ms |
| D. NUS → Bukit Panjang, KFC preferred | Exact KFC (+20.93) plus allowed easier fried-chicken alternatives; preference remained soft | 7 | 67.05 ms |
| E. NUS → Bukit Panjang, must be KFC | KFC only (+19.05); no substitute business appeared | 6 | 35.41 ms |
| F. Jurong East → Tampines, bubble tea under 10 min max | Closest option +13.92 min, explicitly marked unmet rather than a valid exact match | 7 | 111.83 ms |
| G. Punggol → Orchard, coffee if convenient | Optional intent preserved and a coffee suggestion was returned; baseline remains available | 8 | 47.11 ms |
| H. rare/impossible request | Unsupported terms produce a focused clarification; known two-errand requests use partial/substitute fallbacks before genuine failure | covered by automated tests | — |
| I. discovery search | `burger`, `bakery`, `Popeyes`, and `pharmacy` returned bounded category/brand/place matches. `USB electronics` returned none because that combined term is not supported by the catalog | endpoint + browser | <1 s locally |

Raw discovery results initially revealed that some independent pharmacy names retained an
OSM `node/<id>` suffix. The V0.7.2 response boundary now removes those suffixes and
deduplicates the cleaned labels; a regression test protects the consumer output.

## Visual inspection

- Desktop retains the full-height journey panel and route map, with the discovery palette
  collapsed by default.
- Mobile orders journey form → map → result, has no horizontal overflow or nested catalog
  scrollbar, and keeps primary controls thumb-sized.
- Before a journey the map shows Singapore; it then focuses origin, fits From/To, and after
  optimisation fits A, numbered stop markers, B, baseline and recommended route geometry.
- The recommended line is solid green and the direct baseline is dashed grey.
- Result cards show quality, stop name/context, added time/walking/transfers, dwell estimate,
  baseline versus errand journey, and an actionable navigation handoff. Developer diagnostics
  do not appear.
- No browser console errors or warnings were observed in the interactive run.

## Performance comparison

The same six deterministic benchmark cases were run before and after V0.7.2.

| Metric | V0.5/V0.7.1 baseline | V0.7.2 |
|---|---:|---:|
| Average route calls | 8 | 8 |
| Worst route calls | 9 | 9 |
| Cache-hit rate | 7.69% | 7.69% |
| p50 optimisation latency | 36.89 ms | 46.19 ms |
| p95 optimisation latency | 48.36 ms | 49.81 ms |
| Winner stops lacking context | not measured (examples leaked “unavailable”) | 0 |

The bounded fallback ladder did not increase route-call counts. Local CPU/SQLite timings
vary between runs, but the final p95 remained essentially level. The hard ceiling remains
12 uncached provider requests. The broader seven-case intent matrix used 6–10 calls.

## Known limitations

- Mock route geometry and timing are deterministic approximations; live routing remains
  separately gated.
- Area/station context is deterministic evidence, not entrance-level indoor navigation.
- Opening hours are sparse; unknown hours are not presented as open.
- `USB electronics` is not a canonical combined discovery term, although general electronics
  POIs exist.
- Optional errands are suggested when a usable option exists; the baseline is still returned,
  but there is no dedicated “skip this errand” control yet.
- Product-owner manual acceptance remains required before merge. No deployment was performed.
