import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, Page, test } from "@playwright/test";

import {
  commonRoutes,
  comparedResult,
  intent,
  lotOneStop,
  openPlanner,
  originField,
  recommendation,
  resolvedIntent,
  resolveJourney,
  resultWith,
  walkingAlternative,
} from "./fixtures";

/* The visual-review harness: walks the states a design review looks at and
 * saves a screenshot of each, per project, to ../outputs/ui-review/<project>.
 * Responses come from fixtures.ts, in the shape the app reads today.
 *
 *   CAPTURE_VISUALS=1 npx playwright test e2e/visual-review.spec.ts
 */

test.skip(!process.env.CAPTURE_VISUALS, "Run explicitly with CAPTURE_VISUALS=1");

const secondStop = {
  ...lotOneStop,
  name: "Hillion Mall",
  display_name: "Hillion Mall",
  coordinate: { latitude: 1.3783, longitude: 103.7634 },
  location_context: "Hillion Mall",
  businesses: [
    {
      display_name: "KOI Thé",
      canonical_brand: "KOI Thé",
      category_labels: ["Bubble tea"],
      location_context: "Hillion Mall",
    },
  ],
  dwell_minutes: 8,
};
/** Two errands at two places, so the timeline numbers its stops. */
const multiStop = resultWith({
  best_overall: {
    ...recommendation,
    stops: [
      { ...lotOneStop, businesses: [lotOneStop.businesses[0]], dwell_minutes: 15 },
      secondStop,
    ],
    consolidated: false,
    stop_relationship: "nearby_separate_stores",
    route_geometry: [
      recommendation.route_geometry[0],
      lotOneStop.coordinate,
      secondStop.coordinate,
      recommendation.route_geometry[2],
    ],
  },
  least_walking: walkingAlternative,
});

const conflict = {
  status: "needs_clarification",
  intent: { ...intent, original_text: "bubble tea then Orchard MRT" },
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
      reason: "Destination conflict",
    },
  ],
};

async function shoot(page: Page, output: string, name: string) {
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(output, `${name}.png`) });
}

test("capture the UI review states", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const output = path.resolve(process.cwd(), "..", "outputs", "ui-review", testInfo.project.name);
  mkdirSync(output, { recursive: true });

  let parseBody: unknown = resolvedIntent;
  let optimizeBody: unknown = comparedResult;
  await commonRoutes(page);
  await page.route("**/api/intent/parse", (route) => route.fulfill({ json: parseBody }));
  await page.route("**/api/optimize-intent", (route) => route.fulfill({ json: optimizeBody }));

  await openPlanner(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shoot(page, output, "A-empty");

  await resolveJourney(page);
  await page.getByLabel("What do you need on the way?").fill("KFC and bubble tea");
  await shoot(page, output, "B-resolved-input");

  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();
  await page.waitForTimeout(900);
  await shoot(page, output, "C-result");

  await page.getByRole("button", { name: /Show all \d+ routed options/ }).click();
  await page.locator(".detour").scrollIntoViewIfNeeded();
  await shoot(page, output, "D-compared-options");

  await page.locator(".timeline").scrollIntoViewIfNeeded();
  await shoot(page, output, "E-timeline");

  await page
    .getByRole("button", { name: /Edit journey/ })
    .first()
    .click();
  optimizeBody = multiStop;
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByTestId("recommendation-sheet")).toBeVisible();
  await page.waitForTimeout(900);
  await shoot(page, output, "F-two-stops");

  await page
    .getByRole("button", { name: /Edit journey/ })
    .first()
    .click();
  parseBody = conflict;
  await page.getByLabel("What do you need on the way?").fill("bubble tea then Orchard MRT");
  await page.getByRole("button", { name: /Find best stop/ }).click();
  await expect(page.getByText("Your journey changed")).toBeVisible();
  await shoot(page, output, "G-destination-conflict");

  await openPlanner(page);
  await page.getByRole("button", { name: "Browse categories" }).click();
  await page.getByLabel("Search brands, shops or categories").fill("kfc");
  await expect(page.getByRole("listbox")).toBeVisible();
  await shoot(page, output, "H-category-browser");

  await openPlanner(page);
  await originField(page).fill("chuachukang");
  await expect(page.getByRole("option").first()).toBeVisible();
  await shoot(page, output, "I-location-autocomplete");
});
