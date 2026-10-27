import { expect, test } from "@playwright/test";

/* The service worker against the production build. Every navigation used to
 * be cached under "/", so offline the privacy page opened the planner, and
 * the cache name never changed, so each deploy's hashed assets piled up. */

test("offline, each page opens as itself from a cache named for this build", async ({
  page,
  context,
}) => {
  await page.route("https://www.onemap.gov.sg/**", (route) => route.fulfill({ status: 204 }));
  await page.goto("/");
  // Registered a moment after load, then claims the page.
  await expect
    .poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), {
      timeout: 20_000,
    })
    .toBe(true);
  const script = await page.evaluate(() => navigator.serviceWorker.controller?.scriptURL ?? "");
  const build = new URL(script).searchParams.get("v");
  expect(build).toBeTruthy();
  expect(build).not.toBe("dev");

  // Visited online, so cached under its own URL.
  await page.goto("/privacy/");
  await expect(page.getByRole("heading", { name: "Privacy and data sources" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "More categories" })).toBeVisible();

  const caches = await page.evaluate(() => window.caches.keys());
  expect(caches.sort()).toEqual([`assets-${build}`, `shell-${build}`]);

  await context.setOffline(true);
  await page.goto("/privacy/");
  await expect(page.getByRole("heading", { name: "Privacy and data sources" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "What do you need on the way?",
  );
  await context.setOffline(false);
});
