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

test("a typed request is planned end to end on the real network", async ({ page }) => {
  await choose(page, "Origin", "Punggol", /Punggol/);
  await choose(page, "Destination", "Orchard", /Orchard/);
  await page
    .getByLabel("What do you need on the way?")
    .fill("need to grab panadol and some groceries, prefer FairPrice");
  await page.getByRole("button", { name: "Find best stop" }).click();

  const planner = page.locator("#planner");
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
  await page.getByRole("button", { name: "Leave later", exact: true }).click();
  const time = page.getByLabel("Departure time in Singapore");
  await expect(time).not.toHaveValue("");
  expect(Date.parse(`${await time.inputValue()}:00+08:00`)).toBeGreaterThan(Date.now());
});

test("an example plans a real journey in one tap, drawn line by line", async ({ page }) => {
  await page.getByRole("button", { name: /Punggol.*Orchard/ }).click();
  const planner = page.locator("#planner");
  await expect(planner.getByText(/^arrive \d{1,2}:\d{2}/)).toBeVisible({ timeout: 30_000 });

  // The diagram: the direct trip as the yardstick, then routed options on it.
  await expect(planner.locator(".detour-row.direct")).toBeVisible();
  expect(await planner.locator(".detour-row.option").count()).toBeGreaterThanOrEqual(2);
  // The selected option's first ride is the North East Line, in its colour.
  const ride = planner.locator(".detour-row.selected .piece.ride").first();
  await expect(ride).toHaveCSS("background-color", "rgb(153, 0, 170)");

  // On the map each ride is its own path in its line's colour: NE, then NS.
  const strokes = await page
    .locator(".leaflet-overlay-pane path.route-ride")
    .evaluateAll((paths) => paths.map((path) => path.getAttribute("stroke")));
  expect(strokes).toContain("#9900aa");
  expect(strokes).toContain("#d42e12");
});

test("the timeline's clock times run in order and end at the headline arrival", async ({
  page,
}) => {
  await page.getByRole("button", { name: /Punggol.*Orchard/ }).click();
  const planner = page.locator("#planner");
  const headline = planner.locator(".result-impact em");
  await expect(headline).toHaveText(/^arrive \d/, { timeout: 30_000 });
  const clocks = (await planner.locator(".timeline-clock").allTextContents()).filter(Boolean);
  const minutes = clocks.map((clock) => {
    const [, h, m, half] = clock.match(/(\d{1,2}):(\d{2})\s*(am|pm)/i) ?? [];
    return ((Number(h) % 12) + (half.toLowerCase() === "pm" ? 12 : 0)) * 60 + Number(m);
  });
  for (let index = 1; index < minutes.length; index += 1)
    expect(minutes[index]).toBeGreaterThanOrEqual(minutes[index - 1]);
  expect(`arrive ${clocks[clocks.length - 1]}`).toBe(await headline.textContent());
});
