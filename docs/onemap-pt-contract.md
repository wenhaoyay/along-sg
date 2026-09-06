# OneMap public-transport contract — live validation

## Evidence

Live authentication and public-transport probing succeeded on **2026-08-26 (Asia/Singapore)**.

The sanitised capture in `backend/fixtures/live/2026-08-26T195357/` contains 24 bounded requests: 17 accepted route responses and 7 rejected contract experiments. A secret audit confirmed that configured credential values and authentication fields are not present in the committed fixtures.

## Required live request contract

The smallest successful public-transport request observed used:

    GET /api/public/routingsvc/route
    start=<latitude,longitude>
    end=<latitude,longitude>
    routeType=pt
    date=MM-DD-YYYY
    time=HH:MM:SS
    mode=TRANSIT
    Authorization: <backend token>

Observed requirements:

- date is required and must use MM-DD-YYYY.
- ISO YYYY-MM-DD is rejected.
- time is required and must use 24-hour HH:MM:SS.
- mode is required for routeType=pt.
- Accepted mode values are TRANSIT, BUS, and RAIL.
- Authentication uses the backend token; authentication succeeded and no token was persisted.

## Parameter experiments

| Experiment | Live result | Observed behaviour |
|---|---|---|
| Only start/end/routeType=pt | Rejected, HTTP 400 | Requested a date in MM-DD-YYYY. |
| Date as YYYY-MM-DD plus time | Rejected, HTTP 400 | Explicitly rejected the date format. |
| MM-DD-YYYY plus time, no mode | Rejected, HTTP 400 | Requested mode; listed transit, bus, rail. |
| MM-DD-YYYY, time, TRANSIT | Accepted, HTTP 200 | Returned one itinerary. |
| Missing time | Rejected, HTTP 400 | Requested HH:MM:SS 24-hour time. |
| Invalid time | Rejected, HTTP 400 | Explicitly rejected the time format. |
| Invalid calendar date | Rejected, HTTP 400 | Explicitly rejected the date. |
| mode=TRANSIT | Accepted | Returned mixed public transit chosen by the router. |
| mode=BUS | Accepted | Returned bus-only transit legs. |
| mode=RAIL | Accepted | Returned subway-only transit legs for the reference journey. |
| Invalid mode | Rejected, HTTP 400 | Returned the accepted-values message. |
| maxWalkDistance=250 | Accepted but no observed effect | Returned 536.77 m walking and walkLimitExceeded=false. |
| maxWalkDistance=2000 | Accepted but no observed effect | Returned the identical route and walking total. |
| maxWalkDistance=-1 | Accepted but no observed effect | Returned the identical route; validation/enforcement was not observed. |
| numItineraries=1 | Accepted | Returned one itinerary. |
| numItineraries=3 | Accepted but no observed effect | Still returned exactly one identical itinerary. |

Production therefore sends only the smallest verified contract. It does not send maxWalkDistance or numItineraries, because accepting those query parameters did not demonstrate that OneMap honors them.

## Departure-time behaviour

Departure-time routing is verified.

For the same Punggol MRT → Orchard MRT route on 2026-08-27:

| Requested time | Returned start | Returned end | Duration | Waiting | Transit | Walking |
|---|---|---|---:|---:|---:|---:|
| 08:00:00 | 08:00:46 | 08:40:21 | 2,375 s | 260 s | 1,584 s | 531 s |
| 18:00:00 | 18:00:46 | 18:39:30 | 2,324 s | 209 s | 1,584 s | 531 s |

Changing departure time changed waiting and total duration while leaving transit and walking time unchanged. Returned starts were shortly after the requested departure. ONEMAP_DEPARTURE_TIME_ROUTING_VERIFIED is therefore enabled, and onward errand segments are requested after the preceding arrival plus configured dwell time.

## Observed response schema

All 17 successful responses used these top-level fields:

    debugOutput
    elevationMetadata
    metadata
    nextPageCursor
    plan
    previousPageCursor
    requestParameters

plan contained date, from, itineraries, and to.

Every observed itinerary contained:

    arrivedAtDestinationWithRentedBicycle
    duration
    elevationGained
    elevationLost
    endTime
    fare
    generalizedCost
    legs
    startTime
    tooSloped
    transfers
    transitTime
    waitingTime
    walkDistance
    walkLimitExceeded
    walkTime

All legs shared timing, distance, endpoint, geometry, mode and realtime/pathway fields. Transit legs additionally contained agency, route, service, trip and intermediate-stop fields. Walking legs additionally contained rented-bike/walking-bike fields.

No null value was observed anywhere inside the returned itinerary trees in this capture. Fields remain optional in the normalizer because availability can differ by route/mode and the upstream contract is external.

## Verified units and semantics

### Duration and time

- Itinerary duration, walkTime, transitTime, waitingTime, and leg duration are seconds.
- For every accepted fixture, duration equaled (endTime - startTime) / 1000.
- For every accepted fixture, duration equaled walkTime + transitTime + waitingTime.
- Leg durations exclude inter-leg waiting; itinerary waiting accounts for the difference.
- startTime and endTime are 13-digit Unix epoch milliseconds.
- Normalized times are timezone-aware and converted to Asia/Singapore.

### Distance and walking

- Leg distance and itinerary walkDistance behave as metres.
- For every accepted fixture, itinerary walkDistance equaled the sum of all WALK leg distances within floating-point tolerance.
- Walking time similarly equaled the sum of WALK leg durations.
- maxWalkDistance did not behave as an enforced cap, so the application does not claim or simulate that precision.

### Transfers

- The explicit itinerary transfers value matched number of non-WALK transit legs minus one in every accepted fixture.
- A single bus or subway leg returned zero transfers.
- Two transit legs returned one; three returned two.
- The normalizer uses the explicit value and retains transit-leg inference only as a defensive fallback.

### Geometry

- Every observed leg had legGeometry as an object with length and points.
- points was an encoded-polyline string.
- Both walking and transit legs used this representation.
- The normalized model labels it encoded_polyline; optimizer code never reads upstream geometry fields.

### Itineraries

- Every successful response contained exactly one itinerary.
- Requesting three did not change the count.
- The normalizer records the count and deterministically selects index zero.

## Representative routes tested

All routes used TRANSIT, a departure of 08:00 on 2026-08-27, and the accepted live contract.

| Coverage | Journey | Observed transit | Duration | Walking | Transfers | Provider latency |
|---|---|---|---:|---:|---:|---:|
| MRT-focused | Jurong East → Raffles Place | EW subway | 1,511 s | 29 s / 27.74 m | 0 | 82.14 ms |
| Bus-only | NUS University Town → Holland Village | Bus 95 | 1,813 s | 952 s / 1,023.33 m | 0 | 7,234.87 ms |
| Two-line rail journey | Punggol → NUS | NE + CC subway | 3,852 s | 1,509 s / 1,721.45 m | 1 | 72.20 ms |
| Transfer-heavy rail | Woodlands → HarbourFront | NS + CC subway | 3,584 s | 235 s / 260.01 m | 1 | 76.48 ms |
| Long-distance mixed | Changi Airport → Tuas Link | Bus 34 + CG + EW subway | 6,346 s | 965 s / 1,142.27 m | 2 | 93.75 ms |

The planned bus-plus-MRT Punggol → NUS case was observed as two subway lines. The long-distance Changi → Tuas route supplied the actual mixed bus/MRT coverage. This records returned modes rather than preserving expected labels.

## Normalizer and regression posture

OneMapNormalizer is the only code that reads response field names. The optimizer, API models and UI consume only normalized RouteResult and RouteLeg.

The ordinary deterministic suite loads every accepted definitive live fixture and verifies duration against timestamp delta, walking time/distance against WALK legs, transfer semantics, 13-digit timestamps, encoded geometry structure, and successful normalization.

Every rejected live fixture is asserted to produce an explicit invalid-response error. Fixture regressions do not call OneMap and are safe for ordinary CI.

## Failure handling not observed live

Authentication success and HTTP 400 validation failures were observed live. This probe did not intentionally trigger rate limits, timeouts, upstream 5xx responses or no-route cases. Those paths remain covered with bounded deterministic transport tests and are not represented as live findings.
