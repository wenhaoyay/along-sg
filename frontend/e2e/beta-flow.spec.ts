import { expect, Page, test } from "@playwright/test";

const cck = {
  label: "Choa Chu Kang MRT Station",
  address: "10 Choa Chu Kang Avenue 4",
  postal_code: "689810",
  entity_type: "station",
  confirmed: true,
  coordinate: { latitude: 1.3854, longitude: 103.7443 },
};
const fajar = {
  label: "Fajar LRT Station",
  address: "Fajar Road",
  postal_code: "677728",
  entity_type: "station",
  confirmed: true,
  coordinate: { latitude: 1.3845, longitude: 103.7708 },
};
const orchard = {
  label: "Orchard MRT",
  address: "Orchard Road",
  entity_type: "station",
  confirmed: true,
  coordinate: { latitude: 1.3043, longitude: 103.8322 },
};
const intent = {
  schema_version: "1.0",
  original_text: "KFC and bubble tea",
  required_errands: [
    { category: "fried_chicken", required: true, exact_brand: "KFC", substitutes_allowed: false },
    { category: "bubble_tea", required: true, substitutes_allowed: true },
  ],
  optional_errands: [],
  preferences: {
    walking_tolerance: "low",
    transfer_tolerance: "standard",
    prefer_consolidated_stops: true,
    urgency: "normal",
  },
  parse_method: "deterministic",
  confidence: 0.98,
};
const recommendation = {
  label: "Best Overall",
  quality_label: "Best option",
  match_classification: "best_match",
  hard_constraints_satisfied: true,
  stops: [
    {
      name: "Lot One",
      display_name: "Lot One",
      coordinate: { latitude: 1.3851, longitude: 103.7449 },
      matching_outlets: ["KFC · fried_chicken", "KOI Thé · bubble_tea"],
      businesses: [
        {
          display_name: "KFC",
          canonical_brand: "KFC",
          category_labels: ["Fried chicken"],
          location_context: "Lot One",
        },
        {
          display_name: "KOI Thé",
          canonical_brand: "KOI Thé",
          category_labels: ["Bubble tea"],
          location_context: "Lot One",
        },
      ],
      semantic_type: "mall",
      location_context: "Lot One",
      context_kind: "mall",
      location_quality: 0.95,
      navigation_ready: true,
    },
  ],
  consolidated: true,
  total_duration_minutes: 37,
  total_walking_distance_m: 510,
  total_transfers: 0,
  incremental_detour_minutes: 8,
  incremental_walking_distance_m: 180,
  incremental_transfers: 0,
  stop_relationship: "same_mall",
  why_this_wins: "Both errands are in one mall near the route.",
  detour_breakdown: {
    extra_transport_minutes: 8,
    dwell_minutes: 23,
    dwell_allowances: [
      { label: "Estimated fried chicken stop", minutes: 15 },
      { label: "Estimated bubble tea stop", minutes: 8 },
    ],
    total_incremental_minutes: 31,
    precision_note: "Travel comes from the route check. Stop times are practical estimates.",
  },
  route_geometry: [cck.coordinate, { latitude: 1.3851, longitude: 103.7449 }, fajar.coordinate],
  legs: [
    {
      mode: "WALK",
      duration_minutes: 4,
      distance_m: 300,
      from_name: "Origin",
      to_name: "CHOA CHU KANG MRT",
      route_short_name: null,
      route_long_name: null,
      agency: null,
      stop_count: null,
      segment_index: 0,
    },
    {
      mode: "SUBWAY",
      duration_minutes: 11,
      distance_m: 5200,
      from_name: "CHOA CHU KANG MRT",
      to_name: "BUKIT PANJANG",
      route_short_name: "DT",
      route_long_name: "DOWNTOWN LINE",
      agency: "SBS Transit",
      stop_count: 4,
      segment_index: 0,
    },
    {
      mode: "BUS",
      duration_minutes: 8,
      distance_m: 2600,
      from_name: "LOT ONE",
      to_name: "FAJAR LRT",
      route_short_name: "190",
      route_long_name: "SBST BUS 190",
      agency: "SBS Transit",
      stop_count: 3,
      segment_index: 1,
    },
    {
      mode: "WALK",
      duration_minutes: 3,
      distance_m: 210,
      from_name: "FAJAR LRT",
      to_name: "Destination",
      route_short_name: null,
      route_long_name: null,
      agency: null,
      stop_count: null,
      segment_index: 1,
    },
  ],
};
const walkingAlternative = {
  ...recommendation,
  quality_label: "Less walking",
  match_classification: "best_match",
  stops: [
    {
      ...recommendation.stops[0],
      name: "Hillion Mall",
      display_name: "Hillion Mall",
      coordinate: { latitude: 1.3783, longitude: 103.7634 },
      location_context: "Hillion Mall",
    },
  ],
  incremental_detour_minutes: 12,
  incremental_walking_distance_m: 60,
  route_geometry: [cck.coordinate, { latitude: 1.3783, longitude: 103.7634 }, fajar.coordinate],
};
const result = {
  origin: cck,
  destination: fajar,
  baseline: {
    duration_minutes: 29,
    walking_distance_m: 330,
    transfers: 0,
    geometry: [cck.coordinate, fajar.coordinate],
  },
  recommendations: {
    best_overall: recommendation,
    fastest: recommendation,
    least_walking: recommendation,
  },
  outcome: "ok",
  message: null,
};

async function commonRoutes(page: Page) {
  await page.route("https://www.onemap.gov.sg/maps/tiles/**", (route) =>
    route.fulfill({ status: 204 }),
  );
  await page.route("**/api/catalog/categories", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          slug: "fried_chicken",
          name: "Fried chicken",
          parent_slug: "fast_food",
          outlet_count: 125,
        },
        {
          slug: "japanese_food",
          name: "Japanese food",
          parent_slug: "food_drink",
          outlet_count: 44,
        },
      ]),
    }),
  );
  await page.route("**/api/catalog/search**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          display_name: "Sakura Independent Kitchen",
          kind: "place",
          canonical_brand: null,
          categories: ["japanese_food"],
          outlet_count: 1,
          example_location: "Clementi",
        },
      ]),
    }),
  );
  await page.route("**/api/discovery/needs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "Japanese",
        semantic_type: "category",
        canonical_concept: null,
        category: null,
        confidence: "likely",
        related_terms: [],
        places: [],
        live_fallback_used: false,
      }),
    }),
  );
  await page.route("**/api/geocode**", (route) => {
    const url = new URL(route.request().url());
    const q = url.searchParams.get("q")?.toLowerCase() ?? "";
    const matches = q.includes("chua")
      ? [cck, { ...cck, label: "Choa Chu Kang Bus Interchange" }]
      : q.includes("fajar")
        ? [fajar]
        : q.includes("orchard")
          ? [orchard]
          : [];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ query: q, results: matches, provider: "mock" }),
    });
  });
}

async function resolveJourney(page: Page) {
  await page.getByLabel("Origin").fill("chuachukang");
  await page.getByRole("option").first().getByRole("button").click();
  await page.getByLabel("Destination").fill("Fajar");
  await page.getByRole("option").first().getByRole("button").click();
  await expect(page.getByLabel("Location selected")).toHaveCount(2);
}

test("partial requests require consent and mobile sheets resize", async ({ page, isMobile }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({ json: { status: "resolved", intent, unresolved_terms: ["shoe repair"] } }),
  );
  let calls = 0;
  await page.route("**/api/optimize-intent", (route) => {
    calls++;
    return route.fulfill({ json: result });
  });
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and shoe repair");
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect(page.getByText("We found part of your request")).toBeVisible();
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "Continue with matched errands" }).click();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
  expect(calls).toBe(1);
  await expect(page.getByText(/min added in total/)).toBeVisible();
  await expect(page.getByText(/Hours not confirmed/).first()).toBeVisible();
  if (isMobile) {
    await page.getByRole("button", { name: "Map", exact: true }).click();
    await expect(page.getByTestId("recommendation-sheet")).toBeHidden();
    await page.getByRole("button", { name: "Details", exact: true }).click();
    await expect(page.getByTestId("recommendation-sheet")).toBeVisible();
    await expect(page.getByRole("button", { name: "Details", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  }
});

test("scheduled departure uses Singapore offset and stop selection stays in sync", async ({
  page,
}) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({ json: { status: "resolved", intent } }),
  );
  let departure: string | null = null;
  await page.route("**/api/optimize-intent", (route) => {
    departure = route.request().postDataJSON().departure;
    return route.fulfill({ json: result });
  });
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("Departure mode").selectOption("later");
  await page.getByLabel("Departure time in Singapore").fill("2099-09-08T10:30");
  await page.getByLabel("What do you need on the way?").fill("KFC");
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
  expect(departure).toBe("2099-09-08T10:30:00+08:00");
  const stop = page.getByRole("button", { name: "Highlight stop 1: Lot One" });
  await stop.click();
  await expect(stop).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".along-marker.stop.selected-stop")).toHaveCount(1);
});

test("cancelled searches cannot replace a later result and preserve the journey", async ({
  page,
}) => {
  await commonRoutes(page);
  let release: (() => void) | undefined;
  let attempts = 0;
  await page.route("**/api/intent/parse", async (route) => {
    attempts++;
    if (attempts === 1)
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    await route.fulfill({ json: { status: "resolved", intent } }).catch(() => {});
  });
  await page.route("**/api/optimize-intent", (route) => route.fulfill({ json: result }));
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC");
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect.poll(() => attempts).toBe(1);
  await page.getByRole("button", { name: "Cancel search" }).click();
  await expect(page.getByLabel("What do you need on the way?")).toHaveValue("KFC");
  await expect(page.getByLabel("Location selected")).toHaveCount(2);
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
  release?.();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
});

test("failed discovery offers explicit related searches without claiming stock", async ({
  page,
}) => {
  await commonRoutes(page);
  await page.route("**/api/catalog/search**", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/discovery/needs**", (route) =>
    route.fulfill({
      json: {
        semantic_type: "product",
        places: [],
        related_terms: ["printer ink", "printer supplies"],
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Browse categories" }).click();
  await page.getByLabel("Search brands, shops or categories").fill("printer ink");
  await expect(page.getByText(/check cartridge compatibility/)).toBeVisible();
  await page.getByRole("button", { name: "Search printer supplies" }).click();
  await expect(page.getByLabel("Search brands, shops or categories")).toHaveValue(
    "printer supplies",
  );
});

test("failed comparison can be retried without reentering the journey", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({ json: { status: "resolved", intent } }),
  );
  let calls = 0;
  await page.route("**/api/optimize-intent", (route) => {
    calls++;
    return calls === 1
      ? route.fulfill({ status: 503, json: { detail: "busy" } })
      : route.fulfill({ json: result });
  });
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC");
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect(page.getByText("Journey checks are busy. Try again shortly.")).toBeVisible();
  await expect(page.getByLabel("What do you need on the way?")).toHaveValue("KFC");
  await page.getByRole("button", { name: "Retry search" }).click();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
  expect(calls).toBe(2);
});

test("journey swap and walking preference reach the optimizer", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "resolved", intent }),
    }),
  );
  let submitted:
    | {
        origin: { coordinate: { latitude: number } };
        intent: { preferences: { walking_tolerance: string } };
      }
    | undefined;
  await page.route("**/api/optimize-intent", (route) => {
    submitted = route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(result),
    });
  });
  await page.goto("/");
  await resolveJourney(page);
  await page.getByRole("button", { name: "Reverse journey" }).click();
  await expect(page.getByLabel("Origin", { exact: true })).toHaveValue("Fajar LRT Station");
  await page.getByRole("button", { name: "Less walking", exact: true }).click();
  await expect(page.getByRole("button", { name: "Less walking", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByLabel("What do you need on the way?").fill("KFC");
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
  expect(submitted?.origin.coordinate.latitude).toBe(fajar.coordinate.latitude);
  expect(submitted?.intent.preferences.walking_tolerance).toBe("minimal");
});

test("resolved journey produces a hub-first map recommendation", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent,
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
  await expect(page.getByText("KFC · KOI Thé")).toBeVisible();
  await expect(page.getByRole("button", { name: "Navigate" })).toBeVisible();
  // The headline now carries an "extra travel" label of its own, so assert on
  // the breakdown itself rather than on a phrase that appears in both places.
  await expect(page.locator(".breakdown-list")).not.toBeVisible();
  await page.getByText("Why this option").click();
  await expect(page.locator(".breakdown-list")).toBeVisible();
  await expect(page.locator(".breakdown-list")).toContainText("Extra travel");
  await expect(page.getByText("Other options")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(
    /routing calls|provider latency|candidate count|best_match|hard constraints/i,
  );
  await expect(page.getByRole("region", { name: "Journey map" })).toBeVisible();
  await expect(page.locator(".along-marker")).toHaveCount(3);
  await expect(page.locator(".along-marker.origin")).toContainText("A");
  await expect(page.locator(".along-marker.stop")).toContainText("1");
  await expect(page.locator(".along-marker.destination")).toContainText("B");
  await expect(page.locator(".leaflet-overlay-pane path")).toHaveCount(2);
  await expect(page.locator("body")).not.toContainText(/node\/|way\/|relation\//);
  if (test.info().project.name === "mobile-chromium") {
    const sheet = await page
      .getByRole("complementary", { name: "Recommendation", exact: true })
      .boundingBox();
    const map = await page.getByRole("region", { name: "Journey map" }).boundingBox();
    expect(sheet?.y).toBeGreaterThan(250);
    expect(map?.height).toBeGreaterThan(600);
  }
});

test("different alternatives stay collapsed until requested", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent,
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...result,
        recommendations: { best_overall: recommendation, least_walking: walkingAlternative },
      }),
    }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByText("Hillion Mall")).not.toBeVisible();
  await page.getByText("Other options").click();
  await expect(page.getByText("Hillion Mall")).toBeVisible();
  await expect(page.getByRole("button", { name: /Less walking/ })).toHaveCount(1);
  // An alternative that reads better on the headline number must say what it
  // costs, or the ranking looks broken.
  await expect(page.getByText(/less walking/i).last()).toBeVisible();
  await expect(page.locator(".alternative-tradeoff")).toContainText(
    /m (less|more) walking|min (less|more) travel/,
  );
});

test("location autocomplete supports keyboard selection", async ({ page }) => {
  await commonRoutes(page);
  await page.goto("/");
  const origin = page.getByLabel("Origin");
  await origin.fill("chuachukang");
  await expect(page.getByRole("listbox")).toBeVisible();
  await origin.press("ArrowDown");
  await origin.press("Enter");
  await expect(page.getByLabel("Location selected")).toHaveCount(1);
});

test("destination conflict blocks optimization until a user chooses", async ({ page }) => {
  await commonRoutes(page);
  let optimizeCalls = 0;
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "needs_clarification",
        intent: { ...intent, original_text: "bubble tea" },
        clarification_question:
          "Your destination above is Fajar LRT Station, but your request mentions Orchard MRT.",
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [
          {
            endpoint: "destination",
            current_label: "Fajar LRT Station",
            mentioned_text: "Orchard MRT",
            mentioned_label: "Orchard MRT",
            latitude: 1.3043,
            longitude: 103.8322,
            reason:
              "Your destination above is Fajar LRT Station, but your request mentions Orchard MRT.",
          },
        ],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) => {
    optimizeCalls += 1;
    return route.abort();
  });
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("bubble tea then go Orchard MRT");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByText("Your journey changed")).toBeVisible();
  await expect(page.getByRole("button", { name: "Keep Fajar LRT Station" })).toBeVisible();
  expect(optimizeCalls).toBe(0);
});

test("non-errands are explained and the structured catalog is live", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "unresolved",
        intent: null,
        clarification_question:
          "I couldn't find an errand in that request. Try ‘KFC and bubble tea’.",
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("I like cats");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByText(/couldn't find an errand/)).toBeVisible();
  await page.getByRole("button", { name: /Browse categories/ }).click();
  await page.getByLabel("Search brands, shops or categories").fill("Japanese");
  await expect(page.getByText("Sakura Independent Kitchen")).toBeVisible();
  await page.getByRole("listbox").getByRole("option").click();
  await expect(page.getByRole("button", { name: "Required" })).toBeVisible();
});

test("privacy notice remains available without an account", async ({ page }) => {
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { name: "What the beta uses and keeps" })).toBeVisible();
});

test("discovery shows a dish concept and evidenced place", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/discovery/needs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "mee pok",
        semantic_type: "dish",
        canonical_concept: "Mee pok",
        category: "japanese_food",
        confidence: "strong",
        related_terms: ["mee pok"],
        places: [
          {
            display_name: "Ah Hoe Mee Pok",
            coordinate: { latitude: 1.38, longitude: 103.75 },
            address: "Teck Whye",
            mall_or_hub: "Teck Whye Market",
            category: "japanese_food",
            confidence: "strong",
            evidence: ["mee pok"],
          },
        ],
        live_fallback_used: false,
      }),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /Browse categories/ }).click();
  await page.getByLabel("Search brands, shops or categories").fill("mee pok");
  await expect(page.getByText("Dish · 1 matching place")).toBeVisible();
  await expect(page.getByText("Ah Hoe Mee Pok")).toBeVisible();
});

test("open-world compound errands remain plausible and reach optimization", async ({ page }) => {
  await commonRoutes(page);
  const openCompound = {
    ...intent,
    original_text: "Meepok and panadol",
    required_errands: [
      {
        category: "open_meepok_1",
        required: true,
        substitutes_allowed: true,
        discovery_concept: "Meepok",
        discovery_category: "restaurants",
        open_need: { raw_text: "Meepok", inferred_type: "dish", resolution_status: "resolved" },
      },
      {
        category: "open_panadol_2",
        required: true,
        substitutes_allowed: true,
        discovery_concept: "panadol",
        discovery_category: "pharmacy",
        open_need: { raw_text: "panadol", inferred_type: "product", resolution_status: "resolved" },
      },
    ],
  };
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent: openCompound,
        diagnostics: { discovered_need_count: 2 },
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("Meepok and panadol");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByRole("heading", { name: "Lot One" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("couldn't find an errand");
});

test("product discovery labels category matches without claiming stock", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/catalog/search**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/discovery/needs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "Panadol",
        semantic_type: "product",
        canonical_concept: "Panadol",
        category: "pharmacy",
        confidence: "likely",
        related_terms: ["panadol", "pharmacy"],
        places: [
          {
            display_name: "Guardian",
            coordinate: { latitude: 1.304, longitude: 103.832 },
            address: "Orchard Road",
            mall_or_hub: "ION Orchard",
            category: "pharmacy",
            confidence: "likely",
            evidence_tier: "supported",
            suitability: "category_likely",
            provenance: ["local_catalog"],
          },
        ],
        warnings: [
          "These businesses are relevant to the product category; current item-level stock is not guaranteed.",
        ],
      }),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /Browse categories/ }).click();
  await page.getByLabel("Search brands, shops or categories").fill("Panadol");
  await expect(page.getByText("Stock not guaranteed")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/in stock|available now/i);
});

test("a stop whose shops share an hours state says so once", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent,
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();

  // Two shops, both unknown: one grouped line, not the same caveat twice.
  await expect(page.locator(".hours-status")).toHaveCount(1);
  await expect(page.locator(".hours-status")).toContainText("Hours not confirmed for both");
});

test("a mixed hours stop names each shop", async ({ page }) => {
  await commonRoutes(page);
  const mixed = {
    ...recommendation,
    stops: [
      {
        ...recommendation.stops[0],
        businesses: [
          { ...recommendation.stops[0].businesses[0], opening_status: "open" },
          { ...recommendation.stops[0].businesses[1], opening_status: "unknown" },
        ],
      },
    ],
  };
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent,
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...result, recommendations: { best_overall: mixed } }),
    }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();

  await expect(page.locator(".hours-status")).toHaveCount(2);
  await expect(page.locator(".hours-status").first()).toContainText("KFC:");
  await expect(page.locator(".hours-status").last()).toContainText("KOI Thé:");
});

test("the headline is extra travel and the total is stated separately", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent,
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();

  // extra_transport_minutes is 8 and dwell 23, so the headline reads 8 and the
  // dwell is disclosed rather than folded into it.
  await expect(page.locator(".result-impact > strong")).toContainText("+8");
  await expect(page.locator(".result-impact > strong")).toContainText("extra travel");
  await expect(page.locator(".impact-caption")).toContainText("~23 min at your stops");
  await expect(page.locator(".impact-caption")).toContainText("added in total");
});

test("the theme button cycles auto, light and dark, and the choice survives a reload", async ({
  page,
}) => {
  await commonRoutes(page);
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");

  const toggle = page.locator(".theme-toggle");
  const theme = () => page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  const preference = () => toggle.getAttribute("data-theme-preference");

  // A light device with no stored choice follows the device.
  await expect(toggle).toBeVisible();
  expect(await preference()).toBe("system");
  expect(await theme()).toBe("light");

  await toggle.click();
  expect(await preference()).toBe("light");
  await toggle.click();
  expect(await preference()).toBe("dark");
  // The override beats the device, which is still light.
  expect(await theme()).toBe("dark");
  await expect(page.locator('meta[name="theme-color"]').first()).toHaveAttribute(
    "content",
    "#0c1211",
  );

  await page.reload();
  await expect(toggle).toBeVisible();
  expect(await theme()).toBe("dark");
  expect(await preference()).toBe("dark");

  // Back to auto returns to the device scheme and forgets the choice.
  await toggle.click();
  expect(await preference()).toBe("system");
  expect(await theme()).toBe("light");
  expect(await page.evaluate(() => localStorage.getItem("along-theme"))).toBeNull();
});

test("a dark device with no stored choice renders dark before paint", async ({ page }) => {
  await commonRoutes(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // Asserted at DOMContentLoaded: the blocking bootstrap must have run already,
  // otherwise the page paints light and flips.
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe(
    "dark",
  );
  await expect(page.locator(".theme-toggle")).toHaveAttribute("data-theme-preference", "system");
});

test("the timeline names the service you board, per segment", async ({ page }) => {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent,
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();

  const rides = page.locator(".ride-leg");
  await expect(rides).toHaveCount(2);
  // Rail reads as a line, bus as a numbered service, each with stops ridden.
  await expect(rides.nth(0)).toContainText("DT line");
  await expect(rides.nth(0)).toContainText("4 stops");
  await expect(rides.nth(1)).toContainText("Bus 190");
  await expect(rides.nth(1)).toContainText("3 stops");
  // Walking legs are not services and must not appear.
  expect((await rides.allTextContents()).join(" ")).not.toMatch(/walk/i);
  // Segment 0's service sits above the stop, segment 1's below it.
  const rideOne = await rides.nth(0).boundingBox();
  const stopRow = await page.locator(".stop-summary-row").first().boundingBox();
  const rideTwo = await rides.nth(1).boundingBox();
  expect(rideOne!.y).toBeLessThan(stopRow!.y);
  expect(rideTwo!.y).toBeGreaterThan(stopRow!.y);

  // The endpoints name the places the user chose, not the coordinates sent.
  await expect(page.locator(".timeline-endpoint").first()).toContainText("Choa Chu Kang");
  await expect(page.locator(".timeline-endpoint").first()).not.toContainText(/\d+\.\d{4},/);
});

test("markers that would overlap are fanned apart", async ({ page }) => {
  await commonRoutes(page);
  // The stop sits ~30 m from the origin - a mall built on top of the station.
  const onStation = {
    ...result,
    recommendations: {
      best_overall: {
        ...recommendation,
        stops: [
          {
            ...recommendation.stops[0],
            coordinate: {
              latitude: cck.coordinate.latitude + 0.0002,
              longitude: cck.coordinate.longitude,
            },
          },
        ],
      },
    },
  };
  await page.route("**/api/intent/parse", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "resolved",
        intent,
        diagnostics: {},
        journey_mentions: [],
        journey_conflicts: [],
      }),
    }),
  );
  await page.route("**/api/optimize-intent", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(onStation),
    }),
  );
  await page.goto("/");
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();
  await page.waitForTimeout(1800);

  // Both the origin and the stop must carry an offset, or one hides the other.
  const fanned = await page
    .locator(".along-marker > span")
    .evaluateAll(
      (els) =>
        els.filter(
          (el) =>
            getComputedStyle(el).getPropertyValue("--fan-y").trim() ||
            getComputedStyle(el).getPropertyValue("--fan-x").trim(),
        ).length,
    );
  expect(fanned).toBeGreaterThanOrEqual(2);

  // And they must end up visually separated on screen. Measured on the inner
  // span: Leaflet owns the outer element's position, and the fan offset is
  // applied to the glyph inside it.
  const boxes = await page
    .locator(".along-marker > span")
    .evaluateAll((els) =>
      els.map((el) => el.getBoundingClientRect()).map((r) => ({ x: r.x, y: r.y })),
    );
  const gaps = [];
  for (let i = 0; i < boxes.length; i += 1)
    for (let j = i + 1; j < boxes.length; j += 1) {
      gaps.push(Math.hypot(boxes[i].x - boxes[j].x, boxes[i].y - boxes[j].y));
    }
  expect(Math.min(...gaps)).toBeGreaterThan(20);
});
