import { expect, Page, test } from "@playwright/test";
import { commonRoutes, openPlanner, planJourney } from "./fixtures";

/* The screens' words have a budget, and the form fits the first screen.
 *
 * Taglines, helper lines and secondary labels crept in one at a time, each
 * reasonable on its own, until the planner's main field sat under the fold
 * and the result said the same thing four ways. This counts the words a
 * visitor reads that are not a control - buttons, links and fields are
 * actions, not prose - and fails when a screen grows past its budget.
 *
 * Over budget? Each line on screen should be a fact about this trip, an
 * action or a warning. If a screen needs a line to make sense, change the
 * layout instead (see frontend/CLAUDE.md). Raise a budget only for a new
 * fact, and say which in the commit. */

const BUDGET = {
  home: 15,
  result: 150,
};

/** Visible words outside controls, in reading order, with the lines they came from. */
async function prose(page: Page) {
  return page.locator("main").evaluate((root) => {
    const controls = "button, a, input, textarea, select, [role=option], [role=button]";
    const ignored = ".sr-only, .leaflet-control-container, .leaflet-marker-pane";
    const lines: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const element = node.parentElement;
      if (!element || element.closest(controls) || element.closest(ignored)) continue;
      if (!element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
      const box = element.getBoundingClientRect();
      if (!box.width || !box.height) continue;
      const words = (node.textContent ?? "")
        .split(/\s+/)
        .filter((word) => /[\p{L}\p{N}]/u.test(word));
      if (words.length) lines.push(words.join(" "));
    }
    return { count: lines.join(" ").split(" ").length, lines };
  });
}

/** Whether an element is wholly inside the viewport, and not under the sticky button. */
async function inFirstScreen(page: Page, selector: string) {
  const box = await page.locator(selector).first().boundingBox();
  const viewport = page.viewportSize();
  return Boolean(box && viewport && box.y >= 0 && box.y + box.height <= viewport.height);
}

test.describe("copy budget", () => {
  // Words and layout are the same in every theme: one desktop and one phone run.
  test.beforeEach(({}, testInfo) => {
    test.skip(!["desktop-chromium", "mobile-chromium"].includes(testInfo.project.name));
  });

  test("the input screen stays within its words, with the form on the first screen", async ({
    page,
  }, testInfo) => {
    if (testInfo.project.name === "desktop-chromium")
      await page.setViewportSize({ width: 1280, height: 800 });
    await commonRoutes(page);
    await openPlanner(page);
    const { count, lines } = await prose(page);
    testInfo.annotations.push({ type: "words", description: String(count) });
    expect(count, `Over budget. On screen:\n${lines.join("\n")}`).toBeLessThanOrEqual(BUDGET.home);

    // The need field, both journey fields and the button, with no scrolling.
    const need = await page.getByLabel("What do you need on the way?").boundingBox();
    const find = await page.getByRole("button", { name: /Find best stop/ }).boundingBox();
    const to = await page.getByRole("combobox", { name: /^(To|Destination)$/ }).boundingBox();
    const height = page.viewportSize()?.height ?? 0;
    expect(need && need.y + need.height <= height, "the need field is below the fold").toBe(true);
    expect(to && find && to.y + to.height <= find.y, "To is under the Find button").toBe(true);
    expect(find && find.y + find.height <= height, "Find is below the fold").toBe(true);
  });

  test("a result stays within its words", async ({ page }, testInfo) => {
    if (testInfo.project.name === "desktop-chromium")
      await page.setViewportSize({ width: 1280, height: 800 });
    await planJourney(page);
    await page.waitForTimeout(800);
    const { count, lines } = await prose(page);
    testInfo.annotations.push({ type: "words", description: String(count) });
    expect(count, `Over budget. On screen:\n${lines.join("\n")}`).toBeLessThanOrEqual(
      BUDGET.result,
    );
    expect(await inFirstScreen(page, ".result-impact")).toBe(true);
  });
});
