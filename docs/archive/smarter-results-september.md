# Smarter results and mobile controls

Implemented locally in September 2026:

- Store-level opening-hours warnings at estimated stop arrival, including a warning if the estimated dwell crosses closing time. Per-stop arrival is retained only when the routing provider supports time-dependent departures. No additional routing requests are required.
- Visible direct-versus-with-stops duration comparison and an explanation that added journey time includes estimated dwell.
- Explicit consent before optimising the understood subset of an otherwise unresolved request. The missing terms and matched errands remain visible, with an edit action.
- Mobile Map, Summary and Details sheet positions. Controls are keyboard-accessible; collapsed content is removed from the mobile focus order. Desktop retains the existing panel.

## Opening-hours limitations

This is advisory, not an opening-hours filter or a ranking penalty. It does not guarantee that a business is open or has stock. It uses store hours, never substitutes mall hours, and does not fetch new hours or infer missing data.

The conservative parser supports `24/7`, daily time intervals, individual weekday and weekday-range intervals, and overnight intervals. Times are interpreted in Asia/Singapore. Unsupported holiday rules, overlapping rules, ambiguous intervals and missing hours/time support return `unknown`. Listed schedules may be stale and holiday exceptions are not verified. Dwell is the whole stop allowance rather than a precise shop-by-shop arrival inside a mall.

## Verification

Deterministic tests cover Singapore-time conversion, overnight intervals, closing boundaries, missing data, unsupported syntax, and provider time-support gating. Browser regression tests cover explicit partial-request consent, visible comparisons, unknown-hours messaging, and mobile collapse/expand controls. No new live API findings are claimed for this change.
