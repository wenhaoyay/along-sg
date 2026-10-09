# Remaining recommendation improvements — 7 September 2026

## Implemented

- **Nearby candidates:** evaluate a bounded pool of up to 80 local discovery matches before response truncation. Rank context-relevant places first; equally relevant places are ordered by distance from the supplied route geometry before name. Discovery retains relevance checks and the optimizer retains existing transit routing budgets and scoring weights. A geometry-based proximity rank is not itself a transit detour estimate.
- **Discovery recovery:** product/service searches with no matches expose up to three related-search actions from the resolver. These do not automatically select or substitute a place. Brand/unknown searches do not receive this automatic broadening. Existing required selections stay intact. Stock/service availability and cartridge compatibility are explicitly not guaranteed.
- **Departure planning:** Leave now / Leave later, with an explicitly Singapore-time input and an ISO `+08:00` departure sent to the existing optimizer API. Past/invalid departures are rejected in the UI. Normalized response fields expose supported departure/arrival values; unsupported provider time precision is explicitly flagged.
- **Explanations and timeline:** origin, stop sequence and destination, with available arrival/departure values; concrete stop-relationship and transfer explanations. Stop-card buttons and map markers share selection highlighting. Existing green styling and mobile sheet controls remain.
- **Web evidence:** no longer rename a geocoded mall as a named outlet. Named business grounding must agree with explicit location hints in the web result. Missing independent named-business coordinates means no recommendation from that web lead. This may lower recall, including the previous mall-grounded Molly Tea diagnostic. Historical live results are not evidence that the stricter adapter still returns the same result.
- **Cancel/retry:** browser requests are abortable, stale responses cannot overwrite a newer search, and retry/edit retains journey fields. Cancellation does not promise to terminate already-running upstream/server work; provider budgets still apply.

## Fixed benchmark and review boundary

Run `backend/.venv/Scripts/python.exe backend/tools/benchmark_journeys.py` from the root. It uses an isolated seed-only temporary SQLite catalog, the mock provider, three Singapore origin/destination pairs, and one/two-errand cases at `2026-09-08T10:00:00+08:00`. It never invokes a live provider. JSON includes the catalog hash, weights, selected stops, baseline/total/detour/walking/transfers, routing/cache counters, candidate counts and latency. Human-review fields remain null.

Observed offline run: six of six cases returned recommendations; 7–13 routing calls per case against a hard cap of 18. Two cases exceeded the soft budget of 12 and emitted warnings as intended. Local optimization latency was 2.70–5.01 ms; these are **mock measurements**, not live API performance. Repeatability tests compare selected stops and numerical journey outputs across runs while excluding latency.

Before claiming real-world quality gains, freeze the catalog hash and corpus, capture current live routes with an explicit bounded run, and independently review each selected outlet/address, request relevance, strict-brand compliance, opening-hours practicality, detour and omitted errands. Record reviewer, review date, source evidence, pass/fail and reason per case. Report unresolved cases and latency alongside relevance; never replace these human labels with lexical heuristics. This live/manual acceptance work is still outstanding, and the six-case smoke corpus is not comprehensive coverage.

No deployment or publication is part of these changes.

## Checks executed

- Full backend: 206 passed, 4 explicitly gated integration tests skipped. One existing Starlette/httpx deprecation warning remains.
- Browser regression: 32 passed across mobile and desktop; both visual capture tests were rerun successfully after the final spacing correction. Screenshots use mock responses and blank map tiles, not live map acceptance.
- Frontend ESLint, TypeScript and production build passed.
- Source/exported-bundle credential scan passed; root `.env` is ignored and untracked.
- Six-case offline benchmark and repeatability regression passed. No live provider run or human relevance evaluation was performed for this batch.
