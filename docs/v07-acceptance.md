# V0.7 acceptance record — 2026-08-27

## Delivered

- Mobile-first, no-account journey → natural-language need → interpretation → optimisation → recommendation → external-navigation workflow with one primary action.
- Optional foreground current location, interpretation correction and secondary structured category/brand fallback.
- Inconvenience-first result with deterministic explanation, direct-vs-errand comparison, consolidation wording and deduplicated meaningful Fastest/Least Walking alternatives.
- Recommendation and post-navigation feedback, all requested negative reasons, explicit no-option output and tailored provider/rate/no-route/timeout/unresolved messages.
- Random locally stored anonymous user ID, session/search/event IDs, allowlisted analytics events, 90-day retention, idempotent writes and token-protected aggregate report.
- Static Next.js export and FastAPI API in one Docker image, one 1 GB persistent SQLite volume, offline first-start POI preparation, logical backup script, privacy note and operator runbook.

## Verification evidence

- Backend deterministic suite: **138 passed, 4 skipped** in 13.27 s. The skips are three OneMap and one LLM explicitly gated integration paths.
- Live OneMap gated regression: **3 passed, 138 deselected** in 15.53 s with local credentials; no secrets were displayed or persisted.
- Frontend ESLint: passed.
- Next.js production build, TypeScript checking and static export: passed; `/` and `/privacy` generated.
- Playwright: **16 passed** in mobile Chromium (Pixel 7 profile) and desktop Chromium. Coverage includes the successful recommendation/navigation/negative-feedback event flow, clarification and structured fallback, rate limit, timeout, no route, upstream failure, no convenient option and privacy notice.
- Interactive 412 × 915 combined-app smoke: default Punggol MRT → Orchard MRT groceries + pharmacy request parsed and returned Toa Payoh HDB Hub; the result visibly led with **+36 min**, **no extra transfers**, **+221 m walking**, and **both errands at one stop**. Feedback persisted, privacy loaded and no browser warning/error was observed. Mock optimization used 9 routing calls, 2 cache hits and 83.37 ms total latency.
- Credential scan: passed against source and the generated frontend bundle. `.env`, SQLite files, test/build output and local environments are excluded from Git/build context.
- Deployment smoke: passed static homepage, `/privacy` redirect/page, `/health` and mock `/api/journey`. Consistent SQLite backup smoke passed.

Docker image execution was not possible because Docker is not installed on this workstation. The Dockerfile build stages and Render Blueprint were reviewed against the current official Render Blueprint, Docker, health-check and persistent-disk documentation; the executable combined-process shape was verified without Docker.

## Privacy and storage decision

Journey coordinates and free-form intent are operational request data, not analytics columns. The analytics request rejects unknown fields. Stored events contain only random IDs, server timestamp, allowlisted event type, recommendation key/rank, parse method, bounded latency and allowlisted feedback. The aggregate endpoint is hidden unless `BETA_ADMIN_TOKEN` is configured. SQLite’s online backup API is used for consistent operator backups; backups must remain encrypted/restricted and expire within the event-retention window.

## Acceptance and limitations

V0.7 acceptance criteria are met for a **ready-to-publish private beta**. It is not claimed to be publicly deployed. Manual external actions remain: place the workspace in a private Git repository, connect that repository to Render, enter the two OneMap secrets, deploy, verify the HTTPS URL on a phone and retain the generated admin token securely.

Known limitations remain intentionally unchanged: bounded Singapore POI/catalog coverage, incomplete opening-hours data, no indoor routing, upstream OneMap latency/rate/availability variance, a bounded deterministic grammar unless the optional LLM is configured, external-map navigation behavior, and a single service instance because SQLite uses one persistent disk. Metrics need elapsed time and enough beta traffic before one-day, seven-day and return rates are meaningful. No V0.8 scope was started.
