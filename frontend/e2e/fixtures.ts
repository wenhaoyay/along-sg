import { expect, Page } from "@playwright/test";

/* Stubbed API responses in the current (0.10) shape, shared by the specs that
 * only need a believable journey on screen: the accessibility checks and the
 * visual-review capture. beta-flow.spec.ts keeps its own copies, which its
 * assertions are written against line by line. */

export const cck = {
  label: "Choa Chu Kang MRT Station",
  address: "10 Choa Chu Kang Avenue 4",
  postal_code: "689810",
  entity_type: "station",
  confirmed: true,
  coordinate: { latitude: 1.3854, longitude: 103.7443 },
};
export const fajar = {
  label: "Fajar LRT Station",
  address: "Fajar Road",
  postal_code: "677728",
  entity_type: "station",
  confirmed: true,
  coordinate: { latitude: 1.3845, longitude: 103.7708 },
};
export const orchard = {
  label: "Orchard MRT",
  address: "Orchard Road",
  entity_type: "station",
  confirmed: true,
  coordinate: { latitude: 1.3043, longitude: 103.8322 },
};

export const intent = {
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

export const resolvedIntent = {
  status: "resolved",
  intent,
  diagnostics: {},
  journey_mentions: [],
  journey_conflicts: [],
};

const at = (minutes: number) =>
  new Date(Date.UTC(2099, 8, 8, 2, 0) + minutes * 60_000).toISOString();

type Leg = {
  mode: string;
  duration_minutes: number;
  distance_m: number;
  from_name: string | null;
  to_name: string | null;
  route_short_name: string | null;
  route_long_name: string | null;
  agency: string | null;
  stop_count: number | null;
  from_stop_code: string | null;
  to_stop_code: string | null;
  segment_index: number;
  departure_time: string;
  arrival_time: string;
};

function leg(
  mode: string,
  from: number,
  to: number,
  names: [string, string],
  segment: number,
  line: [string, string] | null = null,
  stops: number | null = null,
): Leg {
  return {
    mode,
    duration_minutes: to - from,
    distance_m: (to - from) * (mode === "WALK" ? 80 : 450),
    from_name: names[0],
    to_name: names[1],
    route_short_name: line?.[0] ?? null,
    route_long_name: line?.[1] ?? null,
    agency: line ? "SBS Transit" : null,
    stop_count: stops,
    from_stop_code: null,
    to_stop_code: null,
    segment_index: segment,
    departure_time: at(from),
    arrival_time: at(to),
  };
}

export const lotOneStop = {
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
  dwell_minutes: 23,
  arrival_time: at(6),
};

export const recommendation = {
  label: "Best Overall",
  quality_label: "Best option",
  match_classification: "best_match",
  hard_constraints_satisfied: true,
  offered: true,
  time_dependent: true,
  departure_time: at(0),
  arrival_time: at(66),
  stops: [lotOneStop],
  consolidated: true,
  total_duration_minutes: 66,
  total_walking_distance_m: 510,
  total_transfers: 1,
  incremental_detour_minutes: 31,
  incremental_travel_minutes: 8,
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
  route_geometry: [cck.coordinate, lotOneStop.coordinate, fajar.coordinate],
  legs: [
    leg("WALK", 0, 6, ["Origin", "Lot One"], 0),
    leg("WALK", 29, 33, ["Lot One", "CHOA CHU KANG MRT"], 1),
    leg("SUBWAY", 35, 47, ["CHOA CHU KANG", "BOTANIC GARDENS"], 1, ["CC", "CIRCLE LINE"], 6),
    leg("SUBWAY", 50, 62, ["BOTANIC GARDENS", "FAJAR"], 1, ["CR", "CROSS ISLAND LINE"], 4),
    leg("WALK", 62, 66, ["FAJAR", "Destination"], 1),
  ],
  inconvenience_score: 14,
};

export const walkingAlternative = {
  ...recommendation,
  quality_label: "Less walking",
  stops: [
    {
      ...lotOneStop,
      name: "Hillion Mall",
      display_name: "Hillion Mall",
      coordinate: { latitude: 1.3783, longitude: 103.7634 },
      location_context: "Hillion Mall",
    },
  ],
  incremental_detour_minutes: 35,
  incremental_travel_minutes: 12,
  incremental_walking_distance_m: 60,
  detour_breakdown: { ...recommendation.detour_breakdown, extra_transport_minutes: 12 },
  route_geometry: [cck.coordinate, { latitude: 1.3783, longitude: 103.7634 }, fajar.coordinate],
  legs: [
    leg("WALK", 0, 3, ["Origin", "CHOA CHU KANG"], 0),
    leg("SUBWAY", 4, 14, ["CHOA CHU KANG", "HILLION"], 0, ["JR", "JURONG REGION LINE"], 5),
    leg("WALK", 14, 16, ["HILLION", "Hillion Mall"], 0),
    leg("BUS", 41, 59, ["HILLION", "FAJAR"], 1, ["975", "SBST BUS 975"], 7),
    leg("SUBWAY", 60, 70, ["FAJAR", "FAJAR"], 1, ["EW", "EAST WEST LINE"], 3),
  ],
  total_duration_minutes: 70,
  arrival_time: at(70),
  inconvenience_score: 19,
};

export function compared(
  name: string,
  lat: number,
  lon: number,
  overrides: Record<string, unknown>,
) {
  return {
    ...walkingAlternative,
    offered: false,
    quality_label: "Also compared",
    stops: [
      {
        ...lotOneStop,
        name,
        display_name: name,
        coordinate: { latitude: lat, longitude: lon },
        location_context: name,
      },
    ],
    route_geometry: [cck.coordinate, { latitude: lat, longitude: lon }, fajar.coordinate],
    ...overrides,
  };
}

const baseline = {
  duration_minutes: 35,
  walking_distance_m: 330,
  transfers: 0,
  geometry: [cck.coordinate, fajar.coordinate],
  departure_time: at(0),
  arrival_time: at(35),
  legs: [
    leg("WALK", 0, 4, ["Origin", "CHOA CHU KANG"], 0),
    leg("SUBWAY", 5, 19, ["CHOA CHU KANG", "BUKIT PANJANG"], 0, ["DT", "DOWNTOWN LINE"], 4),
    leg("SUBWAY", 22, 32, ["BUKIT PANJANG", "FAJAR"], 0, ["NS", "NORTH SOUTH LINE"], 3),
    leg("WALK", 32, 35, ["FAJAR", "Destination"], 0),
  ],
};

export function resultWith(recommendations: Record<string, unknown>) {
  return {
    origin: cck,
    destination: fajar,
    baseline,
    recommendations,
    outcome: "ok",
    message: null,
  };
}

/** The plan, one offered alternative and three places compared and routed. */
export const comparedResult = resultWith({
  best_overall: recommendation,
  least_walking: walkingAlternative,
  compared_0: compared("Yew Tee Point", 1.3974, 103.747, {
    detour_breakdown: { ...recommendation.detour_breakdown, extra_transport_minutes: 4 },
    incremental_travel_minutes: 4,
    incremental_walking_distance_m: 900,
    incremental_transfers: 2,
    inconvenience_score: 22,
  }),
  compared_1: compared("Bukit Panjang Plaza", 1.3796, 103.7638, {
    detour_breakdown: { ...recommendation.detour_breakdown, extra_transport_minutes: 20 },
    incremental_travel_minutes: 20,
    incremental_walking_distance_m: 30,
    inconvenience_score: 25,
  }),
  compared_2: compared("Junction 10", 1.3801, 103.7603, {
    detour_breakdown: { ...recommendation.detour_breakdown, extra_transport_minutes: 15 },
    incremental_travel_minutes: 15,
    inconvenience_score: 27,
  }),
});

export const categories = [
  { slug: "fast_food", name: "Fast food", parent_slug: "food_drink", outlet_count: 300 },
  { slug: "fried_chicken", name: "Fried chicken", parent_slug: "fast_food", outlet_count: 125 },
  { slug: "bubble_tea", name: "Bubble tea", parent_slug: "food_drink", outlet_count: 225 },
  { slug: "coffee", name: "Coffee", parent_slug: "food_drink", outlet_count: 1800 },
  { slug: "groceries", name: "Groceries", parent_slug: "shopping", outlet_count: 600 },
  { slug: "pharmacy", name: "Pharmacy", parent_slug: "shopping", outlet_count: 140 },
  { slug: "japanese_food", name: "Japanese food", parent_slug: "food_drink", outlet_count: 44 },
];

export const catalogResults = [
  {
    display_name: "KFC",
    kind: "brand",
    canonical_brand: "KFC",
    categories: ["fried_chicken"],
    outlet_count: 85,
    example_location: "Lot One",
  },
  {
    display_name: "Fried chicken",
    kind: "category",
    canonical_brand: null,
    categories: ["fried_chicken"],
    outlet_count: 125,
    example_location: null,
  },
];

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

/** Tiles, catalog, discovery and the geocoder: everything the input screen asks. */
export async function commonRoutes(page: Page) {
  await page.route("https://www.onemap.gov.sg/maps/tiles/**", (route) =>
    route.fulfill({ status: 204 }),
  );
  await page.route("**/api/catalog/categories", (route) => route.fulfill(json(categories)));
  await page.route("**/api/catalog/search**", (route) => route.fulfill(json(catalogResults)));
  await page.route("**/api/discovery/needs**", (route) =>
    route.fulfill(
      json({
        semantic_type: "unknown",
        canonical_concept: null,
        category: null,
        confidence: "unresolved",
        related_terms: [],
        places: [],
        live_fallback_used: false,
      }),
    ),
  );
  await page.route("**/api/bus-arrivals**", (route) => route.fulfill({ status: 204 }));
  await page.route("**/api/geocode**", (route) => {
    const q = new URL(route.request().url()).searchParams.get("q")?.toLowerCase() ?? "";
    const matches = q.includes("chua")
      ? [cck, { ...cck, label: "Choa Chu Kang Bus Interchange" }]
      : q.includes("fajar")
        ? [fajar]
        : q.includes("orchard")
          ? [orchard]
          : [];
    return route.fulfill(json({ query: q, results: matches, provider: "mock" }));
  });
}

/* The two location fields, by role and name. Their names follow the visible
 * labels ("From", "To"); older builds named them "Origin" and "Destination",
 * and either is accepted so these specs run against both. A suggestion is
 * picked by clicking the option itself. */
export const originField = (page: Page) => page.getByRole("combobox", { name: /^(From|Origin)$/ });
export const destinationField = (page: Page) =>
  page.getByRole("combobox", { name: /^(To|Destination)$/ });

export async function resolveJourney(page: Page) {
  await originField(page).fill("chuachukang");
  await page.getByRole("option").first().click();
  await destinationField(page).fill("Fajar");
  await page.getByRole("option").first().click();
  await expect(page.getByLabel("Location selected")).toHaveCount(2);
}

/** The planner, once React has taken over the page. The catalog is fetched
 *  from an effect, so its request means hydration has finished; typing into
 *  the server-rendered markup before then is lost, which WebKit's slower
 *  development build makes easy to do. */
export async function openPlanner(page: Page) {
  const hydrated = page.waitForRequest(/\/api\/catalog\/categories/);
  await page.goto("/");
  await hydrated;
}

/** From the empty page to a result on screen, with `body` as the answer. */
export async function planJourney(page: Page, body: unknown = comparedResult) {
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) => route.fulfill(json(resolvedIntent)));
  await page.route("**/api/optimize-intent", (route) => route.fulfill(json(body)));
  await openPlanner(page);
  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();
}
