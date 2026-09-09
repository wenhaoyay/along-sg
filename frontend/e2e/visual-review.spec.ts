import { mkdirSync } from "node:fs";
import path from "node:path";

import { test, expect, Page } from "@playwright/test";

test.skip(!process.env.CAPTURE_VISUALS, "Run explicitly with CAPTURE_VISUALS=1");

const cck = { label: "Choa Chu Kang MRT Station", address: "10 Choa Chu Kang Avenue 4", postal_code: "689810", entity_type: "station", confirmed: true, coordinate: { latitude: 1.3854, longitude: 103.7443 } };
const fajar = { label: "Fajar LRT Station", address: "Fajar Road", postal_code: "677728", entity_type: "station", confirmed: true, coordinate: { latitude: 1.3845, longitude: 103.7708 } };
const orchard = { label: "Orchard MRT", address: "Orchard Road", entity_type: "station", confirmed: true, coordinate: { latitude: 1.3043, longitude: 103.8322 } };
const intent = { schema_version: "1.0", original_text: "KFC and bubble tea", required_errands: [{ category: "fried_chicken", required: true, exact_brand: "KFC", substitutes_allowed: false }, { category: "bubble_tea", required: true, substitutes_allowed: true }], optional_errands: [], preferences: { walking_tolerance: "low", transfer_tolerance: "standard", prefer_consolidated_stops: true, urgency: "normal" }, parse_method: "deterministic", confidence: .98 };
const lotOneStop = { name: "Lot One", display_name: "Lot One", coordinate: { latitude: 1.3851, longitude: 103.7449 }, matching_outlets: ["KFC · fried_chicken", "KOI Thé · bubble_tea"], businesses: [{ display_name: "KFC", canonical_brand: "KFC", category_labels: ["Fried chicken"], location_context: "Lot One" }, { display_name: "KOI Thé", canonical_brand: "KOI Thé", category_labels: ["Bubble tea"], location_context: "Lot One" }], semantic_type: "mall", location_context: "Lot One", context_kind: "mall", location_quality: .95, navigation_ready: true };
const baseRecommendation = { label: "Best Overall", quality_label: "Best option", match_classification: "best_match", hard_constraints_satisfied: true, stops: [lotOneStop], consolidated: true, total_duration_minutes: 37, total_walking_distance_m: 510, total_transfers: 0, incremental_detour_minutes: 8, incremental_walking_distance_m: 180, incremental_transfers: 0, stop_relationship: "same_mall", why_this_wins: "Both errands are in one mall near the route.", detour_breakdown: { extra_transport_minutes: 8, dwell_minutes: 23, dwell_allowances: [{ label: "Estimated fried chicken stop", minutes: 15 }, { label: "Estimated bubble tea stop", minutes: 8 }], total_incremental_minutes: 31, precision_note: "Travel comes from the route check. Stop times are practical estimates." }, route_geometry: [cck.coordinate, lotOneStop.coordinate, fajar.coordinate] };
const alternative = { ...baseRecommendation, quality_label: "Less walking", stops: [{ ...lotOneStop, name: "Hillion Mall", display_name: "Hillion Mall", coordinate: { latitude: 1.3783, longitude: 103.7634 }, location_context: "Hillion Mall" }], incremental_detour_minutes: 12, incremental_walking_distance_m: 60 };
const secondStop = { ...lotOneStop, name: "Hillion Mall", display_name: "Hillion Mall", coordinate: { latitude: 1.3783, longitude: 103.7634 }, location_context: "Hillion Mall", businesses: [{ display_name: "KOI Thé", canonical_brand: "KOI Thé", category_labels: ["Bubble tea"], location_context: "Hillion Mall" }] };
const multiRecommendation = { ...baseRecommendation, stops: [{ ...lotOneStop, businesses: [lotOneStop.businesses[0]] }, secondStop], consolidated: false, total_duration_minutes: 43, incremental_detour_minutes: 14, stop_relationship: "nearby_separate_stores", route_geometry: [cck.coordinate, lotOneStop.coordinate, secondStop.coordinate, fajar.coordinate] };

function resultWith(recommendations: Record<string, typeof baseRecommendation>) {
  return { origin: cck, destination: fajar, baseline: { duration_minutes: 29, walking_distance_m: 330, transfers: 0, geometry: [cck.coordinate, fajar.coordinate] }, recommendations, outcome: "ok", message: null };
}

async function resolveJourney(page: Page) {
  await page.getByLabel("Origin").fill("chuachukang");
  await page.getByRole("option").first().getByRole("button").click();
  await page.getByLabel("Destination").fill("Fajar");
  await page.getByRole("option").first().getByRole("button").click();
}

test("capture required V0.7.2 UI review states", async ({ page }, testInfo) => {
  const output = path.resolve(process.cwd(), "..", "outputs", "v072-ui-screenshots", testInfo.project.name);
  mkdirSync(output, { recursive: true });
  let optimizeBody = resultWith({ best_overall: baseRecommendation });
  let conflictMode = false;
  await page.route("https://www.onemap.gov.sg/maps/tiles/**", (route) => route.fulfill({ status: 204 }));
  await page.route("**/api/catalog/categories", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ slug: "fast_food", name: "Food", parent_slug: "food_drink", outlet_count: 300 }, { slug: "fried_chicken", name: "Fried chicken", parent_slug: "fast_food", outlet_count: 125 }, { slug: "bubble_tea", name: "Bubble tea", parent_slug: "food_drink", outlet_count: 225 }, { slug: "coffee", name: "Coffee", parent_slug: "food_drink", outlet_count: 1800 }, { slug: "groceries", name: "Groceries", parent_slug: "shopping", outlet_count: 600 }, { slug: "pharmacy", name: "Pharmacy", parent_slug: "shopping", outlet_count: 140 }]) }));
  await page.route("**/api/catalog/search**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ display_name: "Burger King", kind: "brand", canonical_brand: "Burger King", categories: ["fast_food"], outlet_count: 55, example_location: "Lot One" }]) }));
  await page.route("**/api/discovery/needs**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ semantic_type: "unknown", canonical_concept: null, category: null, confidence: "unresolved", places: [], related_terms: [], live_fallback_used: false }) }));
  await page.route("**/api/geocode**", (route) => { const q = new URL(route.request().url()).searchParams.get("q")?.toLowerCase() ?? ""; const matches = q.includes("chua") ? [cck, { ...cck, label: "Choa Chu Kang Bus Interchange" }] : q.includes("fajar") ? [fajar] : q.includes("orchard") ? [orchard] : []; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ query: q, results: matches, provider: "mock" }) }); });
  await page.route("**/api/intent/parse", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(conflictMode ? { status: "needs_clarification", intent, clarification_question: "Your destination above is Fajar LRT Station, but your request mentions Orchard MRT.", diagnostics: {}, journey_mentions: [], journey_conflicts: [{ endpoint: "destination", current_label: "Fajar LRT Station", mentioned_text: "Orchard MRT", mentioned_label: "Orchard MRT", latitude: 1.3043, longitude: 103.8322, reason: "Destination conflict" }] } : { status: "resolved", intent, diagnostics: {}, journey_mentions: [], journey_conflicts: [] }) }));
  await page.route("**/api/optimize-intent", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(optimizeBody) }));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Find what you need/ })).toBeVisible();
  await page.waitForTimeout(100);
  await page.screenshot({ path: path.join(output, "A-empty.png") });

  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await page.screenshot({ path: path.join(output, "B-resolved-input.png") });

  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();
  await page.waitForTimeout(850);
  await page.screenshot({ path: path.join(output, "C-one-stop.png") });

  await page.getByRole("button", { name: /Edit journey/ }).click();
  optimizeBody = resultWith({ best_overall: multiRecommendation, least_walking: alternative });
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await page.waitForTimeout(850);
  await page.screenshot({ path: path.join(output, "D-multi-errand.png") });

  await page.getByText("Other options").click();
  await page.locator(".planner").evaluate((panel) => { panel.scrollTop = Math.max(0, panel.scrollHeight - panel.clientHeight - 16); });
  await page.screenshot({ path: path.join(output, "E-alternatives-open.png") });

  await page.getByRole("button", { name: /Edit journey/ }).click();
  conflictMode = true;
  await page.getByLabel("What do you need on the way?").fill("bubble tea then Orchard MRT");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByText("Your journey changed")).toBeVisible();
  await page.screenshot({ path: path.join(output, "F-destination-conflict.png") });

  await page.reload();
  await page.getByLabel("Origin").fill("chuachukang");
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.screenshot({ path: path.join(output, "G-location-autocomplete.png") });
});
