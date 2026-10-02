# V0.7.1 manual and adversarial QA

Status: automated checks complete; ready for product-owner manual acceptance.

Run the backend in mock mode and the Next.js frontend, then verify at desktop and mobile
widths. A location is valid only after a suggestion is selected and “Confirmed” appears.

| Case | Input | Expected |
|---|---|---|
| A | From `chuachukang`; To `Fajar`; Need `KFC` | Choa Chu Kang station/interchange suggestions; explicit selection; no unresolved routing. |
| B | Boon Lay → Fajar; `fried chicken and bubble tea` | Human-readable stop/hub, businesses underneath, no raw IDs, bounded routing diagnostics. |
| C | Boon Lay → Fajar; `go to Orchard MRT` | Destination-only guidance; no errand and no optimisation. |
| D | Boon Lay → Fajar; `bubble tea then go Orchard MRT` | Destination conflict with keep/change/edit actions; routing blocked. |
| E | NUS → Fajar; `I'm leaving from Orchard and need coffee` | Origin conflict; routing blocked. |
| F | Any confirmed journey; `I like cats` | “I couldn't find an errand” plus useful examples. |
| G–L | `Japanese food`, `Korean fried chicken`, `printer ink`, `flowers`, `stationery`, `pet food` | Resolve only where the populated catalog supports it; otherwise explicit no/insufficient match, never invention. |
| M | `chuachukang`, `jurongpoint`, `macdonald`, `watson` | Location misspellings produce sensible suggestions; catalog/intent aliases resolve only with sufficient confidence. |
| N | Inspect all ordinary recommendation text and navigation labels | No `node/`, `way/`, `relation/`, source IDs, database IDs or provider IDs. |

Additional visual checks:

- Desktop uses the full viewport with a compact 410 px planner and map-dominant main area.
- Mobile orders the form, map and result vertically; fields and primary action fit without horizontal scrolling.
- OneMap/SLA attribution remains visible at every breakpoint.
- Keyboard focus is visible; suggestions and catalog choices are operable without a pointer.
- Same-mall errands show one place followed by both businesses; separate errands show numbered stops and per-stop navigation.
- The detour explanation reconciles extra transport, category allowances and total inconvenience, with walking/transfers adjacent.
- Current location requests foreground permission only and renders as a confirmed field when granted.

Known manual-review focus: live OneMap search ranking can return several similarly named
addresses; the product intentionally requires selection rather than auto-picking. The
bundled OSM capture does not contain every expanded taxonomy tag, so empty categories are
not shown until a later bounded capture supplies real data.
