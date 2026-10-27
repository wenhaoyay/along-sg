/* The README's pictures, taken from the real app rather than drawn.
 *
 * Needs the production build served with the full catalogue, e.g.
 *
 *   cd backend
 *   .venv\Scripts\python.exe scripts\ingest_osm_pois.py --input data\singapore-osm-pois.json
 *   set SERVE_FRONTEND_DIR=..\frontend\out
 *   .venv\Scripts\python.exe -m uvicorn app.main:app --port 8041
 *
 * then, from frontend/:
 *
 *   node scripts/capture-readme.mjs http://127.0.0.1:8041 ../docs/images
 *   python scripts/frames-to-gif.py ../docs/images/.frames ../docs/images/demo.gif
 *
 * Map tiles come from OneMap, so they need a network; everything else is
 * the app as a visitor sees it. */
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const base = process.argv[2] ?? "http://127.0.0.1:8041";
const out = path.resolve(process.argv[3] ?? "../docs/images");
const frames = path.join(out, ".frames");
rmSync(frames, { recursive: true, force: true });
mkdirSync(frames, { recursive: true });

const browser = await chromium.launch();

async function open(viewport, colorScheme = "light", extra = {}) {
  const page = await browser.newPage({ viewport, colorScheme, ...extra });
  await page.goto(base, { waitUntil: "networkidle" });
  return page;
}

async function runExample(page) {
  await page.getByRole("button", { name: /Punggol.*Orchard/ }).click();
  await page.locator(".result-arrival").waitFor({ timeout: 60_000 });
  await page.waitForTimeout(1800); // the route draws itself
}

// 1. The demo: the empty planner, one tap on an example, the result drawing in.
{
  const page = await open({ width: 960, height: 600 });
  let index = 0;
  const shoot = async (count, gap) => {
    for (let i = 0; i < count; i += 1) {
      await page.screenshot({ path: path.join(frames, `${String(index).padStart(4, "0")}.png`) });
      index += 1;
      await page.waitForTimeout(gap);
    }
  };
  await shoot(8, 120);
  await page.getByRole("button", { name: /Punggol.*Orchard/ }).hover();
  await shoot(6, 120);
  await page.getByRole("button", { name: /Punggol.*Orchard/ }).click();
  await page.locator(".result-arrival").waitFor({ timeout: 60_000 });
  await shoot(26, 90);
  await page.locator("#planner").evaluate((el) => el.scrollTo({ top: 360, behavior: "smooth" }));
  await shoot(18, 110);
  await page.close();
}

// 2. Stills.
{
  const page = await open({ width: 1440, height: 900 });
  await runExample(page);
  await page.screenshot({ path: path.join(out, "result-desktop.png") });
  await page.locator(".detour").screenshot({ path: path.join(out, "detour-diagram.png") });
  await page.locator("#planner").evaluate((el) => el.scrollTo({ top: 760 }));
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, "result-desktop-timeline.png") });
  await page.close();
}
{
  const page = await open({ width: 390, height: 844 }, "light", { isMobile: true, hasTouch: true });
  await runExample(page);
  await page.screenshot({ path: path.join(out, "result-mobile.png") });
  await page.close();
}
{
  const page = await open({ width: 1440, height: 900 }, "dark");
  await page.getByRole("button", { name: /Jurong East.*Raffles/ }).hover();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(out, "home-dark.png") });
  await page.close();
}

await browser.close();
console.log(`Captured into ${out}`);
