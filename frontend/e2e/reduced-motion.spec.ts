import { expect, test } from "@playwright/test";

test("marker landing animation is disabled when reduced motion is requested", async ({ page }) => {
  await page.goto("/privacy");
  await page.evaluate(() => {
    const marker = document.createElement("div");
    marker.className = "along-marker";
    const inner = document.createElement("span");
    marker.appendChild(inner);
    document.body.appendChild(marker);
  });

  const marker = page.locator(".along-marker span");

  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect
    .poll(() => marker.evaluate((element) => getComputedStyle(element).animationName))
    .toBe("marker-land");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect
    .poll(() => marker.evaluate((element) => getComputedStyle(element).animationName))
    .toBe("none");
});
