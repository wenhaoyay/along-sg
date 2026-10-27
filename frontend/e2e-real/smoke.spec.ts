import { expect, Page, test } from "@playwright/test";

/* The production build, served the way the container serves it: each page
 * opens, the manifest is real, and nothing complains in the console. Tiles
 * and OneMap's attribution logo are third-party images and are stubbed, so a
 * machine without that network still passes. */

function collectErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test.beforeEach(async ({ page }) => {
  await page.route("https://www.onemap.gov.sg/**", (route) => route.fulfill({ status: 204 }));
});

test("the planner opens with no console errors", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("button", { name: "More categories" })).toBeVisible();
  await page.waitForTimeout(1500);
  expect(errors).toEqual([]);
});

test("the privacy page opens with no console errors", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/privacy/");
  await expect(page.getByRole("heading", { name: "Privacy and data sources" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("the manifest, icons and sharing tags are served", async ({ page, request }) => {
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBe(true);
  const body = await manifest.json();
  expect(body.name).toBe("Along");
  for (const icon of body.icons as Array<{ src: string }>)
    expect((await request.get(icon.src)).ok(), icon.src).toBe(true);
  for (const path of ["/favicon.ico", "/icon.svg", "/robots.txt"])
    expect((await request.get(path)).ok(), path).toBe(true);

  await page.goto("/");
  const meta = (selector: string) => page.locator(selector).first().getAttribute("content");
  // One colour for the browser chrome, the manifest and the page ground.
  expect(await meta('meta[name="theme-color"]')).toBe(body.theme_color);
  expect(await meta('meta[property="og:title"]')).toBeTruthy();
  expect(await meta('meta[name="twitter:card"]')).toBe("summary_large_image");
  const image = await meta('meta[property="og:image"]');
  expect(image).toMatch(/^https?:\/\/.+\/opengraph-image\.png/);
  const served = await request.get(new URL(image!).pathname);
  expect(served.ok()).toBe(true);
  expect(served.headers()["content-type"]).toContain("image/png");
});
