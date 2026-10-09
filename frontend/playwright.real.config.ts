import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

/* The full stack, nothing stubbed: the real FastAPI backend (mock routing over
 * the real rail network, on its own throwaway seed catalog) serving the real
 * production build of the client, on a port of its own so a running dev
 * setup is untouched.
 * The main suite (playwright.config.ts) stubs every API response; this one
 * exists to catch the client and the API drifting apart.
 *
 *   npm run test:e2e:real          PYTHON=path/to/python to pick the interpreter
 */
const PORT = 8011;
const python =
  process.env.PYTHON ??
  (process.platform === "win32" ? "..\\backend\\.venv\\Scripts\\python.exe" : "python");
const database = path.join(os.tmpdir(), `along-e2e-real-${process.pid}.db`);

export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop-real",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile-real",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
  webServer: {
    // Built and served the way the production container does it: the static
    // export, mounted by FastAPI itself (SERVE_FRONTEND_DIR), page and API on
    // one origin.
    command: `npm --prefix ../frontend run build && "${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: "../backend",
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 300_000,
    env: {
      NEXT_PUBLIC_API_BASE_URL: "",
      ONEMAP_MOCK: "true",
      DATAMALL_MOCK: "true",
      LLM_INTENT_ENABLED: "false",
      DISCOVERY_LIVE_ENABLED: "false",
      DATABASE_PATH: database,
      ANALYTICS_DATABASE_PATH: `${database}.analytics`,
      SERVE_FRONTEND_DIR: path.resolve(__dirname, "out"),
    },
  },
});
