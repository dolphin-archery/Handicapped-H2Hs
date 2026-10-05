import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;
// Serve the build under a sub-path, as GitHub Pages does (/<repo-name>/), to exercise the
// relative asset URLs.
const BASE_PATH = "/Handicapped-H2Hs/";

// https://playwright.dev/docs/test-configuration
export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}${BASE_PATH}`,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    // A phone: iOS Safari's engine, touch, and its 390 x 664 viewport (UISpec.md 7.4).
    { name: "mobile", use: { ...devices["iPhone 13"] } },
  ],
  webServer: {
    // Build first so the tests never run against a stale dist/.
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort --base ${BASE_PATH}`,
    url: `http://localhost:${PORT}${BASE_PATH}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
