# Privacy notes

Along is designed so journey planning can work without user accounts or background location tracking.

## Journey data

The planner sends the origin, destination and errand request to the backend to resolve locations and calculate a recommendation. Choosing **Use my current location** requests one foreground browser location at that moment; the app does not continuously track location.

Journey inputs are not copied into the analytics database. The analytics endpoint accepts a fixed event schema and rejects coordinates and free-form request text.

## Anonymous beta analytics

The browser uses random local and session identifiers. They are not derived from a name, email address, location or device fingerprint.

The stored events are limited to product-flow measurements such as whether a recommendation was returned, selected, opened for navigation or rated. The default retention period is 90 days and can be changed with `ANALYTICS_RETENTION_DAYS`.

Aggregate analytics access requires the backend-only `BETA_ADMIN_TOKEN`.

## External providers

OneMap and optional discovery/LLM credentials stay on the backend and are never exposed through `NEXT_PUBLIC_*` values.

Optional discovery providers receive only the request information needed for the lookup. Web-derived candidates must be grounded to real Singapore coordinates before entering route optimisation.

Opening external navigation is an explicit user action; the selected mapping service's own privacy terms then apply.

## Public data

The bundled place dataset is derived from OpenStreetMap and remains attributed **© OpenStreetMap contributors, ODbL 1.0**.
