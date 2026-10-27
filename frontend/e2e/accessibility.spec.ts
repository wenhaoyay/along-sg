import AxeBuilder from "@axe-core/playwright";
import { expect, Page, test } from "@playwright/test";
import { commonRoutes, openPlanner, planJourney } from "./fixtures";

/* Automated accessibility checks: no serious or critical axe violation on the
 * screens a visitor actually sees. Run in every project, so dark mode and the
 * phone layout are covered by desktop-dark and mobile-dark.
 *
 * axe cannot judge everything - a map is a picture to it, and it cannot tell
 * whether an accessible name is a useful one - so the tests below it check
 * the behaviour that was fixed by hand. */

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    // Leaflet's tiles and vector paths are images of a basemap with no text.
    .exclude(".leaflet-tile-pane")
    .analyze();
  return results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      targets: violation.nodes.slice(0, 5).map((node) => node.target.join(" ")),
    }));
}

test("the input screen has no serious accessibility violations", async ({ page }) => {
  await commonRoutes(page);
  await openPlanner(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(600);
  expect(await seriousViolations(page)).toEqual([]);
});

test("the category browser has no serious accessibility violations", async ({ page }) => {
  await commonRoutes(page);
  await openPlanner(page);
  await page.getByRole("button", { name: "More categories" }).click();
  await page.getByRole("button", { name: "Fast food" }).click();
  await page.getByRole("combobox", { name: "Search brands, shops or categories" }).fill("kfc");
  await expect(page.getByRole("listbox")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("a result has no serious accessibility violations", async ({ page }) => {
  await planJourney(page);
  await page.waitForTimeout(1200);
  expect(await seriousViolations(page)).toEqual([]);
});

test("the privacy page has no serious accessibility violations", async ({ page }) => {
  await page.goto("/privacy/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("the category search is a combobox that says when its list is open", async ({ page }) => {
  await commonRoutes(page);
  await openPlanner(page);
  await page.getByRole("button", { name: "More categories" }).click();
  const search = page.getByRole("combobox", { name: "Search brands, shops or categories" });
  await expect(search).toHaveAttribute("aria-expanded", "false");
  await expect(search).not.toHaveAttribute("aria-controls", /.+/);
  await search.fill("kfc");
  await expect(search).toHaveAttribute("aria-expanded", "true");
  const list = page.getByRole("listbox");
  await expect(list).toBeVisible();
  await expect(search).toHaveAttribute("aria-controls", (await list.getAttribute("id")) ?? "");
  await search.press("ArrowDown");
  const active = await search.getAttribute("aria-activedescendant");
  await expect(page.locator(`#${active}`)).toHaveAttribute("aria-selected", "true");
});

test("preference strength states which is chosen, not only by colour", async ({ page }) => {
  await commonRoutes(page);
  await openPlanner(page);
  await page.getByRole("button", { name: "More categories" }).click();
  await page.getByLabel("Search brands, shops or categories").fill("kfc");
  await page.getByRole("option", { name: /KFC/ }).click();
  const strength = page.getByRole("group", { name: "Preference strength" });
  await expect(strength.getByRole("button", { name: "Preferred" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await strength.getByRole("button", { name: "Any" }).click();
  await expect(strength.getByRole("button", { name: "Any" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // A tap target a thumb can hit, whatever the chip looks like.
  const hit = await strength.getByRole("button", { name: "Any" }).evaluate((element) => {
    const slop = getComputedStyle(element, "::after");
    return element.getBoundingClientRect().height + 2 * -parseFloat(slop.top || "0");
  });
  expect(hit).toBeGreaterThanOrEqual(44);
});

test("closing the category browser with Escape returns focus to its button", async ({ page }) => {
  await commonRoutes(page);
  await openPlanner(page);
  await page.getByRole("button", { name: "More categories" }).click();
  await page.getByLabel("Search brands, shops or categories").press("Escape");
  await expect(page.getByRole("button", { name: "More categories" })).toBeFocused();
});

test("map markers are named for what they are, and only the plan is a tab stop", async ({
  page,
}) => {
  await planJourney(page);
  await page.waitForTimeout(800);
  await expect(
    page.getByRole("button", { name: "Start: Choa Chu Kang MRT Station", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "Destination: Fajar LRT Station", exact: true }),
  ).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Stop 1: Lot One", exact: true })).toHaveCount(1);
  // Compared places are reached from the diagram, not by tabbing over the map.
  const compared = page.locator(".along-marker.considered");
  expect(await compared.count()).toBeGreaterThan(0);
  for (const marker of await compared.all()) {
    await expect(marker).not.toHaveAttribute("tabindex", /.*/);
  }
});
