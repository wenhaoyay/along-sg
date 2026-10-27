# Privacy

What the code does, stated so it can be checked. The in-app page is
`frontend/app/privacy/page.tsx`.

## Journeys

The origin, destination and request text are sent to the server for one
request, to place them, read the request and route the journey. They are not
written to any database. **Current** reads one browser position when it is
tapped, with no background tracking.

## No analytics

The page sends no analytics events and creates no identifier. It stores only
the theme choice in local storage.

The server still has an analytics module from the private-beta period. It is
**off by default** (`ANALYTICS_ENABLED=false`): its routes answer 404 and no
analytics database is created. If an operator turns it on, it accepts only an
allowlisted schema with no coordinates and no free text. It purges events
older than `ANALYTICS_RETENTION_DAYS` every hour and caps the number of rows.
Turning it on would also mean adding a client and rewriting this page and the
in-app notice.

## Logs and limits

The host keeps ordinary access logs. The application logs counts and timings,
not journeys. Per-client rate limits are applied in memory and keep no
record.

## Credentials

- **OneMap and LTA DataMall:** keys and the OneMap token stay on the server,
  and are never named `NEXT_PUBLIC_`.
- **Public demo:** runs with no credentials at all, using offline routing.

## Links out

The Google Maps buttons open only when tapped. They carry the coordinates of
one leg each.

## Data sources

Sources and licences are in [`data-sources.md`](data-sources.md):

- OpenStreetMap (ODbL)
- data.gov.sg / HSA (Singapore Open Data Licence)
- OneMap / SLA
- LTA DataMall
- Wikimedia Commons, for logos
