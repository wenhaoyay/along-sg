# Live optimisation diagnostic

- Live-captured: **yes**
- Run time: 2026-08-26T19:58:00+08:00
- Journey: Punggol MRT → Orchard MRT
- Departure-time routing verified flag: `True`
- Candidate locations: curated Singapore chain outlets in the SQLite seed

## One errand: parcel

- Baseline journey: 40.5 minutes
- Baseline walking: 8.8 minutes / 537 metres
- Baseline transfers: 1
- Routing calls: 9
- Cache hits: 0
- Provider latency: 6682.86 ms
- Generated/pruned/evaluated candidates: 5 / 4 / 4
- Total optimisation latency: 6684.64 ms
- Hard budget reached: False
- Time limitation: none

#### Best Overall

- Hubs: NEX Serangoon
- Outlets: POPStation (parcel)
- Stop relationship: `single_stop`
- Total journey including dwell: 50.1 minutes
- Detour over baseline: 9.7 minutes
- Walking: 13.4 minutes / 831 metres
- Transfers: 1 total / +0 incremental
- Routed segments: 2
- Expected dwell: 8.0 minutes
- Explanation: This option adds one errand stop. Adds 9.7 minutes, 4.6 walking minutes and 0 transfers. Departures after each dwell are re-routed in time sequence.

#### Fastest

- Hubs: NEX Serangoon
- Outlets: POPStation (parcel)
- Stop relationship: `single_stop`
- Total journey including dwell: 50.1 minutes
- Detour over baseline: 9.7 minutes
- Walking: 13.4 minutes / 831 metres
- Transfers: 1 total / +0 incremental
- Routed segments: 2
- Expected dwell: 8.0 minutes
- Explanation: This option adds one errand stop. Adds 9.7 minutes, 4.6 walking minutes and 0 transfers. Departures after each dwell are re-routed in time sequence.

#### Least Walking

- Hubs: NEX Serangoon
- Outlets: POPStation (parcel)
- Stop relationship: `single_stop`
- Total journey including dwell: 50.1 minutes
- Detour over baseline: 9.7 minutes
- Walking: 13.4 minutes / 831 metres
- Transfers: 1 total / +0 incremental
- Routed segments: 2
- Expected dwell: 8.0 minutes
- Explanation: This option adds one errand stop. Adds 9.7 minutes, 4.6 walking minutes and 0 transfers. Departures after each dwell are re-routed in time sequence.

## Two errands: groceries + pharmacy

- Baseline journey: 40.5 minutes
- Baseline walking: 8.8 minutes / 537 metres
- Baseline transfers: 1
- Routing calls: 11
- Cache hits: 2
- Provider latency: 3967.31 ms
- Generated/pruned/evaluated candidates: 55 / 4 / 5
- Total optimisation latency: 3969.66 ms
- Hard budget reached: False
- Time limitation: none

#### Best Overall

- Hubs: ION Orchard
- Outlets: CS Fresh (groceries), Guardian (pharmacy)
- Stop relationship: `same_mall`
- Total journey including dwell: 70.3 minutes
- Detour over baseline: 29.9 minutes
- Walking: 8.7 minutes / 595 metres
- Transfers: 1 total / +0 incremental
- Routed segments: 2
- Expected dwell: 30.0 minutes
- Explanation: Both errands are consolidated inside the same mall. Adds 29.9 minutes, 0.0 walking minutes and 0 transfers. Departures after each dwell are re-routed in time sequence.

#### Fastest

- Hubs: ION Orchard
- Outlets: CS Fresh (groceries), Guardian (pharmacy)
- Stop relationship: `same_mall`
- Total journey including dwell: 70.3 minutes
- Detour over baseline: 29.9 minutes
- Walking: 8.7 minutes / 595 metres
- Transfers: 1 total / +0 incremental
- Routed segments: 2
- Expected dwell: 30.0 minutes
- Explanation: Both errands are consolidated inside the same mall. Adds 29.9 minutes, 0.0 walking minutes and 0 transfers. Departures after each dwell are re-routed in time sequence.

#### Least Walking

- Hubs: ION Orchard
- Outlets: CS Fresh (groceries), Guardian (pharmacy)
- Stop relationship: `same_mall`
- Total journey including dwell: 70.3 minutes
- Detour over baseline: 29.9 minutes
- Walking: 8.7 minutes / 595 metres
- Transfers: 1 total / +0 incremental
- Routed segments: 2
- Expected dwell: 30.0 minutes
- Explanation: Both errands are consolidated inside the same mall. Adds 29.9 minutes, 0.0 walking minutes and 0 transfers. Departures after each dwell are re-routed in time sequence.
