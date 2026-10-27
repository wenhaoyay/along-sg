# How Along ranks a stop

One page on what the planner compares, what it shows, and what each label
means. The code is `backend/app/services/optimizer.py` (scoring and labels),
`candidates.py` (which places get routed) and `explain.py` (the sentence under
the pick).

## The figures

Every option is measured against the trip you were already making, the
**direct** journey from A to B.

| Figure | Meaning | Where it shows |
| --- | --- | --- |
| Extra travel | Extra minutes on trains, buses and on foot. Time in shops is not included. | The headline, every row, every map pin |
| Time in shops | A planning allowance per errand (`DwellTimes` in `config.py`). An ATM is 2 min, a supermarket 15, a haircut 30. | The line under the headline, and each stop's "~15 min here" in the plan |
| Later than direct | Extra travel plus time in shops: how much later you arrive. | The line under the headline, and how far a bar runs past the "direct" line |

Extra travel leads because it is what changes from one place to another. Doing
the same errands takes about the same time wherever you do them. All three
figures come from one module on the page (`journey/figures.ts`), so the
headline, the rows and the pins cannot disagree.

## Choosing what to route

Hundreds of shops can satisfy "groceries", and a live router is slow and
rationed, so only a handful of places are actually routed:

1. **Find candidates.** These are hubs (malls, station areas, shops) that hold
   the errands, within a corridor around the direct route or near either end.
2. **Pair them up.** For two errands, the candidates are every hub that holds
   both, plus pairs of separate hubs. A pair is never padded around a hub that
   already holds both errands.
3. **Prune to the budget.** Candidates are ranked by a network-distance proxy:
   leaving the route there and back, plus the walk to the stop's station. The
   best place beside the origin and the best beside the destination are always
   kept.
4. **Route each survivor** as A, then the stop, then B. A two-stop plan is
   routed in both orders.

`tools/compare_exhaustive.py` measures what pruning costs. It plans 20
journeys as deployed and again with the limits opened wide. The deployed pick
matches the unpruned one on 18 of 20, and the two misses cost at most 1.6
minutes of extra travel.

## Scoring

Each routed option gets one score; lower is better:

```text
score = later-than-direct minutes × 1.0
      + extra walking minutes    × 0.65
      + extra changes            × 6.0
      − location confidence      × 2.5   (address known, mall, station area…)
      − 2.0 if it has the brand you prefer
      − 1.0 if you asked for one stop and it is one stop
```

- **Preference weights.** The request sets them: "minimal walking" raises
  the walking weight, "in a rush" the time weight. On the result, "Faster",
  "Less walking" and "Fewer changes" only re-sort the options already
  routed; the form has no weighting control of its own, because the same
  words meant two different things in two places.
- **Shop time inside the score.** The score uses minutes later than direct,
  which includes time in shops. That only separates options that do
  *different* errands, such as a substitute shop.
- **Opening hours.** A place whose every matching shop is listed as closed
  when you arrive is skipped. Listed hours add confidence only when they say
  open.

## Labels and what they promise

| Label on the pick | It means |
| --- | --- |
| Best option | The lowest score among full matches. |
| Has your preferred brand | It has the brand you said you prefer. |
| Not your preferred brand | No option with that brand came out ahead. |
| Over your limit | Nothing met a limit you marked as strict, such as "max 5 min, strictly". Limits always mean extra travel, never shop time. |

| Tag on another row | It means |
| --- | --- |
| no FairPrice | A full match without your preferred brand. |
| substitute: convenience store | A similar kind of shop instead of the one asked for. Shown only if it gets you there at least 5 min sooner. |
| skips pharmacy | Does only part of the request. Shown next to full matches only if it saves at least 5 min of travel, and it never drops a required errand to keep an "if convenient" one. |

"Fastest" and "Least walking" appear as separate answers only when they beat
the pick by at least 2 minutes or 100 m.

## The sentence under the pick

`explain.py` writes it from the routed options and never from a template.

- **Pick has the least extra travel.** The sentence says what it wins on, for
  example "Of the 4 places compared, it has the least extra travel and the
  least extra walking."
- **A quicker option exists.** The sentence names it and says why the pick
  still ranks first, for example "It has FairPrice, which you prefer. ION
  Orchard is 1 min quicker but has no FairPrice."

The golden-journey tests (`tests/test_golden_journeys.py`) run on the real
catalogue and fail if the explanation claims a win that a compared option
contradicts.
