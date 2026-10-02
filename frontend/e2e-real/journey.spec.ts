import { expect, Page, test } from "@playwright/test";

/* Against the real API (see playwright.real.config.ts): no response is stubbed
 * except the basemap tiles, which are third-party images. The seed catalog
 * holds ten malls with a supermarket and a pharmacy each, Waterway Point and
 * ION Orchard among them. */

test.beforeEach(async ({ page }) => {
  await page.route("https://www.onemap.gov.sg/maps/tiles/**", (route) =>
    route.fulfill({ status: 204 }),
  );
  await page.goto("/");
});

async function choose(page: Page, label: "Origin" | "Destination", text: string, option: RegExp) {
  const field = page.getByLabel(label, { exact: true });
  await field.click();
  await field.pressSequentially(text, { delay: 15 });
  await page.getByRole("option", { name: option }).first().click();
}

async function showSummary(page: Page) {
  // On a phone the result opens as a sheet; the summary is one tap away.
  const summary = page.getByRole("button", { name: "Summary", exact: true });
  if (await summary.isVisible()) await summary.click();
}

test("a typed request is planned end to end on the real network", async ({ page }) => {
  await choose(page, "Origin", "Punggol", /Punggol/);
  await choose(page, "Destination", "Orchard", /Orchard/);
  await page
    .getByLabel("What do you need on the way?")
    .fill("need to grab panadol and some groceries, prefer FairPrice");
  await page.getByRole("button", { name: "Find best stop" }).click();

  const planner = page.locator("#planner");
  await showSummary(page);
  await expect(planner.getByText(/^arrive \d{1,2}:\d{2}/)).toBeVisible({ timeout: 30_000 });
  // The route rides the North East Line out of Punggol - a real line, not
  // one picked by hashing the trip distance.
  await expect(planner.getByText("NE line").first()).toBeVisible();
  await expect(planner.locator(".impact-caption")).toContainText(/min extra travel/);
});

test("a place that does not exist is the user's to fix, with a hint", async ({ page }) => {
  await choose(page, "Origin", "Bishan", /Bishan/);
  await page.getByLabel("Destination", { exact: true }).fill("zzqxv");
  await page.getByLabel("What do you need on the way?").fill("groceries");
  // Caught at the field, against the real geocoder: a hint, and no request
  // that could only fail.
  await expect(page.getByText(/No match for .zzqxv.\. Try a station/)).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("button", { name: "Find best stop" })).toBeDisabled();
});

test("the API itself answers an unknown place with 422, not 502", async ({ request }) => {
  const response = await request.post("/api/optimize", {
    data: {
      origin: { query: "zzqxv" },
      destination: { query: "Bugis MRT" },
      errands: ["groceries"],
    },
  });
  expect(response.status()).toBe(422);
  expect((await response.json()).detail).toMatch(/No Singapore location found/);
});

test("a greeting is not planned as an errand", async ({ page }) => {
  await choose(page, "Origin", "Bishan", /Bishan/);
  await choose(page, "Destination", "Bugis", /Bugis/);
  await page.getByLabel("What do you need on the way?").fill("hello");
  await page.getByRole("button", { name: "Find best stop" }).click();
  await expect(
    page.getByText(/couldn.t find an errand|couldn.t find a reliable place/i),
  ).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText(/^arrive \d/)).toHaveCount(0);
});

test("leave later starts from a time that can be submitted", async ({ page }) => {
  await page.getByLabel("Departure mode").selectOption({ label: "Leave later" });
  const time = page.getByLabel("Departure time in Singapore");
  await expect(time).not.toHaveValue("");
  expect(Date.parse(`${await time.inputValue()}:00+08:00`)).toBeGreaterThan(Date.now());
});
