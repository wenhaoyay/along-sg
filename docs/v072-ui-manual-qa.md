# V0.7.2-UI manual QA

Date: 2026-08-30
Branch: `v0.7.2-apple-ui`

## Scope and principles

This stage changes only the consumer presentation and interaction layer. The optimizer,
OneMap provider boundary, normalized route data and public API contracts remain intact.
The design follows Apple-inspired principles—clarity, deference to content, depth,
direct manipulation and restrained motion—without copying Apple branding, assets,
proprietary typefaces or product layouts.

The map is the persistent spatial context. Desktop uses one compact floating surface;
mobile uses a bounded bottom sheet. Input and result states replace each other in that
surface. The default result answers where to stop and what it costs before offering one
navigation action. Rationale and alternatives are secondary disclosures.

## Visual system

- System sans-serif typography, 29 px desktop / 23 px mobile hero, compact 11 px labels.
- Along green is the only strong accent; neutral GreyLite map and near-white surfaces
  keep the route and selected stop visually dominant.
- 18 px desktop panel and 20 px mobile sheet radii; controls use 9–12 px radii.
- Shadows indicate map/surface depth without glass-heavy decoration.
- Interface motion is 150–240 ms. Map camera moves are bounded to 650–750 ms.
  `prefers-reduced-motion` removes both.
- Lucide icons replace text glyphs for location, search, navigation, status and disclosure.

## Required screenshot matrix

The gated capture workflow writes each state at both 1440×900 and 390×844:

| State | Evidence |
|---|---|
| A | Empty journey planner over the Singapore map |
| B | Resolved From/To and input-ready state |
| C | Successful one-stop recommendation |
| D | Two-errand, two-stop recommendation |
| E | Alternatives disclosure open |
| F | Destination-reference conflict |
| G | Location autocomplete with multiple choices |

Artifacts are local and ignored at
`outputs/v072-ui-screenshots/{desktop-chromium,mobile-chromium}/`. Generate them with:

```powershell
cd frontend
$env:CAPTURE_VISUALS = "1"
npx playwright test e2e/visual-review.spec.ts
```

The ordinary E2E run leaves the visual workflow explicitly skipped.

## Manual browser inspection

The live app was inspected with the official OneMap GreyLite tiles at 1440×900,
1366×768, 1920×1080, 390×844 and 412×915. Verified behaviour:

- map attribution stays visible and the map remains the dominant canvas;
- desktop panel is content-height bounded and scrolls only for long conflict/detail states;
- mobile sheet leaves roughly 40 percent of the map visible and has no page-level or
  horizontal overflow;
- origin autocomplete exposes multiple matches and supports keyboard selection;
- resolved endpoints, one-stop result, route framing and map markers stay synchronized;
- one primary action is visible in each state;
- rationale and alternatives remain collapsed until requested;
- no provider, candidate, scoring or routing-call terminology appears in consumer copy;
- browser console contained no warnings or errors during the inspected journey.

The deterministic screenshot basemap is intentionally flat because tile requests are
intercepted with empty responses. Live-browser inspection separately verifies actual
OneMap tiles and attribution. A visual review identified and corrected development-badge
capture, mobile horizontal overflow, conflict-state scroll position and alternatives
framing before acceptance evidence was recorded.

## Accessibility and interaction notes

- Inputs expose combobox/listbox relationships and selection state.
- Arrow Up/Down, Enter and Escape work in location and discovery result lists.
- Visible focus rings are retained for buttons, links, fields and disclosure summaries.
- Touch targets are generally 44 px or larger for primary controls.
- Motion is disabled for users who request reduced motion.
- Native disclosure elements preserve keyboard and screen-reader behaviour.

## Validation record

- Backend regression: 150 passed, 4 explicitly gated tests skipped.
- Frontend ESLint: passed with no findings.
- Next.js production build and TypeScript: passed; static export generated.
- Functional Playwright: 12 passed across desktop and mobile; the two visual capture
  workflows remained explicitly skipped in the ordinary run.
- Gated visual capture: 2 passed, producing 14 screenshots.
- Combined deployment smoke: passed homepage, privacy redirect/page, health and mock API.
- Live OneMap credentials authenticated. At the actual just-after-midnight departure,
  geocoding/token coverage passed but PT routing returned a genuine HTTP 404 no-route.
  A bounded 09:00 rerun passed direct PT routing and token-cache coverage (2 of 3 tests);
  the optimizer integration's separate baseline call still received an upstream 404.
  No production routing or normalization code was changed for this UI-only stage.

## Known limitations

- This stage does not add drag gestures or multiple bottom-sheet snap points.
- Navigation remains an external map hand-off; it is not turn-by-turn guidance.
- The map route line reflects normalized provider geometry when present and the existing
  fallback point sequence otherwise.
- Visual regression is evidence capture and manual inspection, not pixel-diff enforcement.
