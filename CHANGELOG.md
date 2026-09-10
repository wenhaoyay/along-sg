# Changelog

This file keeps the development milestones out of the main README while preserving the project's progression.

## 0.8.2 - Names a person can read

Idea 3 asked for pictures of the stalls instead of bare names. Measuring the dataset first
found something worse than bare: 3,140 of 9,641 hubs - 32.6% - were displaying a raw
OpenStreetMap element id.

    7-Eleven - node/10030129567
    Bakeries node/10201802661

Two separate defects. `_unique_name` settled a collision by appending the element id, and a
place OSM never named was labelled with its category slug plus the same id. Singapore has
three hundred 7-Elevens and 665 of these places have no name at all, so both branches were
the common path rather than the exceptional one - a third of the catalog introduced itself
to the traveller with a database row number.

Collisions are now settled the way a person settles them: by somewhere you can picture.
The street comes first because it is what somebody standing outside would say, then the
station, then the bus stop reduced to its landmark - "Opposite Haw Par Villa Station"
carries its information in the landmark and its length in the preposition. Only when every
qualifier is taken does it number them, and the element id survives as a last resort that
is now unreachable in practice: 3,140 polluted names became 0, across both hubs and
outlets, with hub, outlet and dedupe counts unchanged.

Places OSM never named get a noun rather than a heading. `CategoryDefinition.name` labels a
group - "Bakeries", "ATM and banking" - and reads as a mistake standing in for one shop, so
`UNNAMED_LABELS` holds the singular separately instead of deriving one from the other.

Three things cost thought. Display and identity had to split: the dedupe key stays keyed on
the element id for an unnamed place, because collapsing it to "Bakery" would merge two
different unnamed bakeries twenty metres apart into one. Qualifiers arrive dirty from both
sources - `addr:street` carries unit numbers punctuated on ("Irving Place, #08-06;The
Commerze@Irving") and stop names carry their own brackets ("T4 Shuttle (Arrival)") which
would nest inside the ones being added - and the brackets have to come off before the comma
split, or "(EW23, CR17)" strands its opening bracket. And the schema's UNIQUE constraint on
(hub_id, name, category) caught what the transform did not: that constraint used to hold by
accident, because an unnamed outlet carried its element id and so could never match another,
and the rebuild failed on it the moment two outlets in one mall were both "Bakery".

What idea 3 actually asked for is not in this data. 20 of 21,280 elements carry an `image`
tag - 0.1% - so photographs are not available from OpenStreetMap at any coverage worth
rendering, and the providers that do have them are paid, uncacheable, or both. Brand logos
are: 601 distinct `brand:wikidata` ids cover 4,077 outlets (19.2%), reachable free and
keyless through Wikidata's EntityData route and Wikimedia Commons. That is the next commit,
and this one had to come first - a logo beside "Bakeries node/10201802661" would have
dressed up the wrong problem.

## 0.8.1 - The static bus network, so an empty answer can explain itself

Added `bus_stops` and `bus_routes` tables, a transform for LTA's BusStops and BusRoutes
datasets, and `scripts/ingest_bus_network.py` to fetch and store them. The arrivals
endpoint now reports the stop's LTA name and, for the service being ridden, whether it is
scheduled to be calling there at all.

That is the difference between "nothing due" and "stopped for the night", which LTA's
front-end advisement names as separate states and which the arrivals feed alone cannot
distinguish - it returns no body for either. Where the timetable is not held the answer
stays `null` rather than `false`, because reporting a service as not running on the
strength of a missing row would invent the very fact this dataset was added to establish.

Three details cost thought. A last bus after midnight is published as a smaller number
than the first ("0015" against "0530"), so the window wraps and a naive comparison marks
the service closed for twenty-three hours a day. `$skip` paging is not documented in
v6.9, so the fetcher stops when a page repeats rather than trusting a page size - a server
ignoring the parameter would otherwise return page one until the cap. And an empty capture
is refused outright: half a bus network is worse than none, because every missing row
reads as a cancelled service.

The client now sends the service it is riding, which both narrows LTA's answer and is what
makes the operating-hours lookup possible at all.

Field names are LTA's own, read from the guide rather than from third-party bindings,
which use different ones. None of this is verified against the live API yet: fetching
requires an AccountKey, so the tests pin the transform and the storage against the
documented shapes.

## 0.8.0 - When the bus is coming, and whether that is a guess

The leg parser was discarding the operator's stop code the same way it had been
discarding service names before 0.7.8. OneMap returns `stopCode` on every transit leg,
and for a bus leg that is the five-digit LTA BusStopCode - so live arrivals join by code
rather than by name or coordinate, and no matching heuristic is involved.

Added an LTA DataMall provider and a `/api/bus-arrivals` endpoint, so the timeline shows
when the next buses on that service are due at the stop you board from. Free: DataMall
allows 10 million calls a day under the Singapore Open Data Licence, which unlike the
place providers weighed up for opening hours permits storing and serving the data on.
Without a key the app serves deterministic sample times, labelled as samples, so the
whole path is developable and testable offline.

Three honesty rules govern it. `Monitored` distinguishes a time derived from the bus's
position from one read off the operator's timetable, and the second is dimmed and
labelled rather than shown in the same voice. Arrivals are requested only for a leg
boarding within the next half hour, because a live time about a bus you will catch in two
hours is a true number about the wrong bus. And durations round down with anything under
a minute shown as arriving, per LTA's own front-end advisement.

Crowding is a coloured dot beside the first time rather than a tint on the times
themselves: LTA permits colouring the timings, but three differently coloured numbers in a
row with no legend reads as urgency, and amber for 8 min beside red for 16 min looks like
a claim about lateness. The level is also given in words for a reader who cannot see the
colour. A stop that answers with nothing says "no live times" without guessing whether
the service has stopped running - telling those apart needs per-stop operating hours from
the Bus Routes dataset, which this app does not hold yet.

## 0.7.11 — Pick your own stop, and say what matters

A compared option is now a recommendation the app did not volunteer, rather than a
second shape: it carries its own stops, legs and geometry, is flagged `offered: false`,
and clicking its map marker or its row in the panel promotes it into the plan. That
replaces the parallel `considered` payload added in 0.7.10 - the moment a compared
option is selectable it needs everything a recommendation needs, at which point the only
difference between the two is whether the app put it forward.

Added a weighting control - our pick, least time, least walking, fewest transfers - which
reorders every routed option and moves the plan to the new leader, because a control that
reshuffled a list while leaving the recommendation contradicting the top of it would be
worse than none. Re-ranking is arithmetic over results that were already routed, so it is
instant and the note under the control says exactly that rather than implying a new
search. No weighting promotes an option that drops an errand: a partial option is cheaper
on every metric by construction, and a live Woodlands-HarbourFront run had a one-errand
option scoring better than every complete one. It stays selectable by hand.

The default is called "our pick" rather than "balanced" because `inconvenience_score` is
the journey cost minus a credit for how confidently the place is known - location
certainty plus published hours, weighted 2.5. On that same run the credit chose a named
shop at +11 min over a mall at +5, which is defensible as a recommendation and
indefensible as a claim about time, walking and transfers.

## 0.7.10 — The map shows the comparison it made

`optimize` routed several candidates and returned only the winners, so a live
Punggol-Orchard run generated 465 candidates, routed 6 and drew 1 marker across most
of a 1440px viewport. The routed-but-rejected candidates are now returned alongside the
recommendations, deduplicated by stop set because a two-stop option is evaluated once per
permutation, and capped at six. The map draws every routed place that is not the plan on
screen - offered alternatives included, since from the map's point of view an alternative
and a rejected candidate are the same thing - and a panel section states what each would
have cost, ordered by the figure it displays and summarised so that six options within a
minute of each other reads as the near-tie it is. Pointing at a row lifts its marker.

Compared options report extra travel rather than total added time, so the number sits
beside the recommendation headline and means the same thing. Fixing that exposed the same
confusion in the alternatives trade-off copy, which compared total added time while
labelling it travel: a live run offered ION Orchard as "15 min less travel" when its
travel differed by 0.15 min and the whole fifteen minutes was one fewer shop to stand in.

## 0.7.9 — Prettier and an enforced line length

Adopted Prettier for the frontend at `printWidth: 100`, matching the backend's ruff
`line-length`, so one number governs both halves of the repository. Every other option is
left at its default because the codebase already wrote double quotes, semicolons and
trailing commas, which keeps the reformat to line-wrapping rather than a rewrite. Wired
`eslint-config-prettier` so ESLint stops competing over the same lines, and added
`@stylistic/max-len` after it, because `printWidth` is a target rather than a ceiling:
Prettier cannot break a comment, a URL or a long string, so those crossed 100 columns
silently. `npm run format` and `npm run format:check` are the entry points. The reformat
itself changes no behaviour - `globals.css` was verified identical once whitespace and
leading zeros are normalised, and the suite passes unchanged.

## 0.7.8 — The timeline names the service you board

Carried `routeShortName`, `routeLongName`, `agencyName` and the intermediate-stop count
through from OneMap, all four of which the leg parser had been discarding, so the timeline
says how to travel between stops instead of only when to be there. Legs now carry a
`segment_index`, because `combine_routes` flattens the routed segments into one list with
no boundary and the client could otherwise only guess which service belongs to which stop;
the mock provider names plausible lines so the timeline is developable offline. Fanned
overlapping map markers around their centre, which the mall recovery made more pressing
rather than less - a Singapore mall is often built on the station, and at Choa Chu Kang the
origin marker was entirely hidden. Raised timeline endpoint contrast, preferred the
client's resolved place names over coordinate-derived labels, and stopped a hub heading
repeating a shop line identical to it.

## 0.7.7 — Honest headline numbers, dark mode and offline shell

Suppressed alternatives whose journey is indistinguishable from the
recommendation - within 2 minutes, 100 m and the same transfer count - so a
second mall is offered only when it is a real choice; an alternative that reads
better on the headline number now states what it costs. Moved the headline from
total added time to extra travel, with in-store time disclosed separately,
because dwell is near-constant across options and was compressing the
difference between them. Collapsed the per-shop opening-hours caveat into one
line when a stop's shops share a state. Added a full dark palette driven by
`prefers-color-scheme`, including inverted map tiles, and tokenised every
remaining hardcoded colour to make it possible; an app-bar button cycles
auto/light/dark, persists the choice and overrides the device, with a blocking
bootstrap script so an override paints correctly on first frame. Added a web manifest, icons and
a service worker so the app installs and its shell opens offline; nothing under
`/api/` is ever cached or replayed, because a stale recommendation is worse than
an error. Renamed the direct-route label from "Straight" to "Direct".

## 0.7.6 — Transit graph coverage and network-aware pruning

Fixed an Overpass transform defect that discarded every way and relation, restoring 244
of 250 mall polygons and 327 further outlets. Widened the capture to bus stops, taking
the transport graph from 132 rail-only nodes to 5,978 and the share of hubs beyond
1,200 m of any node from 45.6% to 0.2%; `station_area` still requires rail within 150 m.
Ranked candidates for the routing budget by distance from the baseline route plus
transit access walk rather than by great-circle distance from the origin-destination
chord. Raised routing concurrency to 4 and the candidate/budget ceilings to match.
Ingested hubs now supersede the curated seed for the same building instead of competing
with it, and prefixed source ids no longer leak into display names.

## 0.7.5 — September journey and discovery improvements

Added Singapore-time departure planning, arrival-aware opening-hours warnings, cancellable/retryable searches, route-proximity candidate ranking, stricter business grounding, related-search recovery, journey timeline/map synchronization, clearer recommendation explanations, mobile result controls and a repeatable six-case offline benchmark.

## 0.7.4 — Open-world discovery

Added plausible free-form need parsing, independent compound resolution, route-corridor place search, bounded TomTom/Geoapify/Tavily escalation and offline discovery evaluation.

## 0.7.3 — Discovery intelligence

Separated location and need resolution, added the LTA rail gazetteer and aliases, SQLite FTS5 search, structured concepts and confidence-triggered live place search.

## 0.7.2 — Consumer UI and fallback behavior

Added the map-first interface, clearer recommendation states, bounded fallback ladder, preference semantics, deterministic location context and more robust alternative ranking.

## 0.7.1 — Product integrity

Added explicit location selection, journey-conflict handling, database-driven catalog search, safer consumer serialization and clearer detour breakdowns.

## 0.7 — Private beta

Added the natural-language workflow, current-location option, anonymous allowlisted analytics, feedback, browser E2E coverage and single-container deployment.

## 0.6 — Intent layer

Added structured intent, deterministic parsing, optional schema-validated LLM fallback and preference-aware scoring.

## 0.5 — POI intelligence

Added the Singapore OSM POI corpus, taxonomy/aliases, mall and transit-node intelligence, staged corridor pruning and route caching.

## 0.4 — Routing hardening

Added OneMap normalization, bounded retries, request budgets, live-contract fixtures, time-aware routing checks and routing diagnostics.

## 0.3 — Two errands

Added same-hub consolidation, separate-stop ordering and objective-specific ranking.

## 0.2 — One errand

Added candidate generation, geometric pruning, branch routing and incremental scoring against the direct journey.

## 0.1 — Baseline journey

Added the OneMap provider abstraction, backend authentication/token caching, geocoding and normalized public-transport journey results with deterministic mock mode.
