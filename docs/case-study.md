# Along: case study

## The problem

Errands get planned around the shop, not around the trip. A maps search answers "where is
the nearest pharmacy?". Someone riding from Punggol to Orchard actually wants to know "where
can I get panadol and groceries **without making this trip much longer**?" The nearest shop
to where you are now is often the wrong answer. The right one is usually beside a station
you were going to pass, or at either end of the trip.

## The product decision

Treat it as a routing problem with a baseline, not a search problem:

- **The direct trip is the yardstick.** Every option is priced as *added* minutes, walking
  and train changes relative to going direct, because that's the cost the traveller feels.
- **The headline is the time you lose.** An earlier version led with "+6 min extra travel"
  and put the 30 minutes in shops in small print. Now the headline is the total added time and
  the arrival, with travel and time at the stops broken out underneath. Extra travel stays
  visible there because it's what differs between options.
- **Being honest beats looking complete.** Opening hours exist for about 20% of outlets; the
  rest say "hours not confirmed" rather than guessing. Bus times without a live key are
  labelled samples. Mock routing never invents a bus number.

## Engineering decisions and trade-offs

**A routing budget, and what it nearly cost.** Routing every candidate would mean hundreds of
OneMap calls per request. Candidates are pruned before routing, using a cheap proxy (distance
from the baseline route plus the walk to transit). The proxy has a blind spot: a mall 400 m
from the origin scores worse than malls sitting right on the line, so Waterway Point, beside
Punggol MRT, was never routed for a Punggol trip. The fix keeps the proxy but always routes the
best stop beside each end of the trip. A test seeds eight on-line malls plus one beside the
origin and asserts that one ranks in the top two. It fails without the fix.

**A mock that tells the truth.** The demo runs without OneMap credentials, so the mock *is* the
product for most people who look at it. It used to name a line by hashing the trip distance,
so Punggol "boarded the NS line". It now runs Dijkstra over a graph built from LTA's own
station codes. Consecutive codes are neighbours, codes shared by one station are interchanges,
and the few links the numbering doesn't express are listed by hand: the Marina Bay spur, the
Changi Airport shuttle, the LRT loops. Lines, interchanges and stop counts are real; only the
minutes are estimates.

**Parsing everyday language without an LLM.** A deterministic parser maps phrases and brands to
categories, and a clause splitter catches needs the taxonomy doesn't know (open discovery).
Real phrasing broke the hand-off: "need to grab panadol and some groceries, prefer FairPrice"
split into three "needs", and because there were more clauses than parsed errands the good
parse was thrown away. Fixes: strip filler words, treat preference clauses as preferences, turn
away greetings, and only fall back to discovery when a clause is one the parser didn't
understand. Measured on 60 tuned phrasings and 20 held-out ones: 74% → 99% and 70% → 95%.

**Errors that belong to the user.** An unknown place used to be an HTTP 502, which says the
server broke. It's a 422 now, with a "did you mean" built from the station gazetteer, and
postal codes resolve offline from catalog addresses.

## How it's verified

- 367 backend tests, including the network-mock, parser, error-code and ranking cases above.
- A phrasing evaluation that CI fails below 90%.
- 164 browser tests with the API stubbed (phone and desktop, light and dark), and 10 that run
  the real API serving the production build, so the client and the API can't drift apart
  unnoticed.

## What I'd do next

- Host the demo (the container and `render.yaml` are ready) and record a handful of live
  OneMap journeys, so live and mock can be compared side by side.
- Split `page.tsx`. The planner's state lives in one large component, and separating it is a
  redesign rather than a file move.
- A "why not X?" answer for when a traveller expects a place the ranking passed over.
