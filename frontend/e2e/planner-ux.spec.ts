import { expect, Page, test } from "@playwright/test";

/* The planner's own behaviour: editing a chosen place, Enter, the search
 * button's reach, share links and Back, focus, and failures that are not
 * JSON. The API is stubbed; the result shape is the smallest one the panel
 * renders. */

const punggol = {
  label: "Punggol MRT",
  entity_type: "mrt_station",
  confirmed: true,
  coordinate: { latitude: 1.4057779, longitude: 103.9028951 },
};
const orchard = {
  label: "Orchard MRT Station",
  entity_type: "mrt_station",
  confirmed: true,
  coordinate: { latitude: 1.3042331, longitude: 103.8316034 },
};
const intent = {
  schema_version: "1.0",
  original_text: "groceries",
  required_errands: [{ category: "groceries", required: true, substitutes_allowed: true }],
  optional_errands: [],
  preferences: {
    walking_tolerance: "standard",
    transfer_tolerance: "standard",
    prefer_consolidated_stops: false,
    urgency: "normal",
  },
  parse_method: "deterministic",
  confidence: 0.9,
};
const recommendation = {
  label: "Best Overall",
  quality_label: "Best option",
  match_classification: "best_match",
  hard_constraints_satisfied: true,
  offered: true,
  stops: [
    {
      name: "Waterway Point",
      display_name: "Waterway Point",
      coordinate: { latitude: 1.4065, longitude: 103.9022 },
      businesses: [],
      matching_outlets: [],
      semantic_type: "mall",
      location_context: "83 Punggol Central",
      context_kind: "address",
      location_quality: 1,
      navigation_ready: true,
      dwell_minutes: 15,
    },
  ],
  consolidated: false,
  total_duration_minutes: 61,
  total_walking_distance_m: 400,
  total_transfers: 1,
  incremental_detour_minutes: 17,
  incremental_travel_minutes: 2,
  incremental_walking_distance_m: 130,
  incremental_transfers: 0,
  stop_relationship: "single_stop",
  why_this_wins: "Of the 3 places compared, it has the least extra travel.",
  detour_breakdown: {
    extra_transport_minutes: 2,
    dwell_minutes: 15,
    dwell_allowances: [{ label: "Estimated supermarket stop", minutes: 15 }],
    total_incremental_minutes: 17,
    precision_note: "Travel comes from the route check.",
  },
  route_geometry: [punggol.coordinate, orchard.coordinate],
  inconvenience_score: 3,
};
const result = {
  origin: punggol,
  destination: orchard,
  baseline: {
    duration_minutes: 44,
    walking_distance_m: 270,
    transfers: 1,
    geometry: [punggol.coordinate, orchard.coordinate],
  },
  recommendations: { best_overall: recommendation },
  outcome: "ok",
  message: null,
};

async function stub(page: Page, optimize?: (route: import("@playwright/test").Route) => unknown) {
  await page.route("https://www.onemap.gov.sg/maps/tiles/**", (route) =>
    route.fulfill({ status: 204 }),
  );
  await page.route("**/api/catalog/categories", (route) => route.fulfill({ json: [] }));
  await page.route("**/health", (route) =>
    route.fulfill({ json: { status: "ok", onemap_mock: true } }),
  );
  await page.route("**/api/geocode**", (route) => {
    const query = new URL(route.request().url()).searchParams.get("q") ?? "";
    const match = /orch/i.test(query) ? orchard : punggol;
    return route.fulfill({ json: { results: [match] } });
  });
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({ json: { status: "resolved", intent, journey_conflicts: [] } }),
  );
  await page.route(
    "**/api/optimize-intent",
    optimize ?? ((route) => route.fulfill({ json: result })),
  );
}

async function choose(page: Page, label: "From" | "To", text: string) {
  const field = page.getByLabel(label, { exact: true });
  await field.fill(text);
  await page.getByRole("option").first().click();
}

async function fillJourney(page: Page) {
  await choose(page, "From", "Punggol");
  await choose(page, "To", "Orchard");
  await page.getByLabel("What do you need on the way?").fill("groceries");
}

test("editing a chosen place keeps what is typed and the focus", async ({ page }) => {
  await stub(page);
  await page.goto("/");
  await choose(page, "From", "Punggol");
  const from = page.getByLabel("From", { exact: true });
  await expect(from).toHaveValue("Punggol MRT");
  await from.click();
  await from.press("End");
  await from.pressSequentially(" Plaza", { delay: 20 });
  // The field used to remount on the first keystroke: empty, focus gone.
  await expect(from).toHaveValue("Punggol MRT Plaza");
  await expect(from).toBeFocused();
});

test("Enter in the need box searches, and Shift+Enter does not", async ({ page }) => {
  let calls = 0;
  await stub(page, (route) => {
    calls += 1;
    return route.fulfill({ json: result });
  });
  await page.goto("/");
  await fillJourney(page);
  const need = page.getByLabel("What do you need on the way?");
  await need.press("Shift+Enter");
  expect(calls).toBe(0);
  await need.press("Enter");
  await expect(page.getByRole("heading", { name: "Waterway Point" })).toBeVisible();
  expect(calls).toBe(1);
});

test("the search button is on screen without scrolling", async ({ page, isMobile }) => {
  test.skip(isMobile, "the phone layout scrolls the sheet by design");
  await stub(page);
  await page.goto("/");
  await fillJourney(page);
  const button = page.getByRole("button", { name: "Find best stop" });
  const box = await button.boundingBox();
  const viewport = page.viewportSize();
  expect(box && viewport && box.y + box.height <= viewport.height).toBeTruthy();
});

test("a plan becomes a link, Back returns to the form, and the link replans", async ({ page }) => {
  await stub(page);
  await page.goto("/");
  await fillJourney(page);
  await page.getByRole("button", { name: "Find best stop" }).click();
  const heading = page.getByRole("heading", { name: "Waterway Point" });
  await expect(heading).toBeVisible();
  // Focus moves to the answer rather than falling to the page.
  await expect(heading).toBeFocused();
  await expect(page).toHaveURL(/\?from=1\.405778%2C103\.902895.*need=groceries/);
  const link = page.url();

  await page.goBack();
  await expect(page.getByRole("button", { name: "Find best stop" })).toBeVisible();
  await page.goForward();
  await expect(heading).toBeVisible();

  const fresh = await page.context().newPage();
  await stub(fresh);
  await fresh.goto(link);
  await expect(fresh.getByRole("heading", { name: "Waterway Point" })).toBeVisible();
  await expect(fresh.getByRole("button", { name: "Share this plan" })).toBeVisible();
});

test("a failure that is not JSON reads as a sentence, not an exception", async ({ page }) => {
  await stub(page, (route) =>
    route.fulfill({ status: 502, contentType: "text/html", body: "<html>Bad gateway</html>" }),
  );
  await page.goto("/");
  await fillJourney(page);
  await page.getByRole("button", { name: "Find best stop" }).click();
  const alert = page.locator(".notice.error");
  await expect(alert).toContainText("We couldn’t check routes right now");
  await expect(alert).not.toContainText(/Unexpected token|JSON/);
});

test("a dropped connection says so", async ({ page }) => {
  await stub(page, (route) => route.abort("connectionreset"));
  await page.goto("/");
  await fillJourney(page);
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect(page.locator(".notice.error")).toContainText("We couldn’t reach Along just now");
});

test("the demo says its times are estimates", async ({ page }) => {
  await stub(page);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Sample times" })).toBeVisible();
});
