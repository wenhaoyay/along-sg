# Private beta privacy note

## What the journey planner uses

The planner sends the origin, destination and errand request to the beta server only to geocode the places, interpret the request and calculate a public-transport recommendation. Choosing **Use my current location** asks the browser for one foreground position at that moment. There is no background or continuous location tracking.

Journey inputs are processed for the current request. They are not copied into the analytics database, and the analytics endpoint rejects extra fields such as coordinates or free-form request text. The web server or hosting platform can still produce short-lived operational access logs; those are not used as journey history.

## Anonymous product analytics

The browser creates a random UUID and retains it in local storage. It is not derived from a device fingerprint, name, email address, IP address or location. A new random session UUID is created for each browser session. The server records only the event type and, where relevant, a random search UUID, recommendation rank/key, parser type, bounded latency, feedback choice or feedback reason.

The beta records enough events to measure whether people understand the flow, receive a recommendation, choose it, open navigation, give feedback and return on another day. It does not require an account and does not store advertising identifiers.

## Retention and access

Analytics events are stored in a separate SQLite database and are deleted after 90 days by default; the period is configurable with `ANALYTICS_RETENTION_DAYS`. Access to the aggregate report requires the server-side `BETA_ADMIN_TOKEN`. OneMap and optional OpenAI credentials also remain server-side and must never use a `NEXT_PUBLIC_` name.

For this private beta, the operator should limit report and backup access to the beta team, keep encrypted backups only as long as operationally required, and delete backups no later than the underlying 90-day event retention window. Removing the site data in the browser resets the anonymous identifier. Because there is no account or identity mapping, the app cannot reliably locate an individual’s events from their real-world identity.

## External navigation and data sources

Navigation opens only after an explicit click and is handled by the user’s selected external mapping service, whose privacy terms then apply. Public place data is derived from OpenStreetMap and remains attributed **© OpenStreetMap contributors, ODbL 1.0**. Public-transport routing and geocoding are supplied through the backend OneMap adapter.

## Optional catalog-gap tracking

V0.7.3 catalog-gap tracking is disabled by default. If the operator explicitly enables
it, only a normalized unresolved need term and aggregate count are retained in process
memory for the admin-only report. It never stores the journey, coordinates, IP address
or arbitrary request history, and it is not written to the analytics database.

## Open-world provider calls

V0.7.4 keeps OneMap, TomTom, Geoapify, Tavily and optional OpenAI credentials server-side;
none may use a `NEXT_PUBLIC_` name. Explicitly enabled discovery providers receive the
specific need phrase and only bounded route-centre/corridor geography when relevance
requires it—not identity, account data or the full journey sentence. Web evidence cannot
enter optimisation until a separate source grounds it to real Singapore coordinates.
Proprietary provider responses use a five-minute in-memory cache and are not persisted.
Raw needs remain excluded from the analytics database; opt-in aggregate gap telemetry
retains the earlier safeguards.
