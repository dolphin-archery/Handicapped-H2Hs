import { test } from "@playwright/test";
import { fixtureDoc, seed } from "./seed";

/**
 * Review screenshots (UILoopPrompt step 4): each route at 1440x900 and 390x844, light and dark,
 * with six seeded events. A `graph` route turns Graph view on and shows every pass's markers. Skipped unless SCREENSHOT_DIR is set, e.g.
 *   $env:SCREENSHOT_DIR = "C:\\temp\\shots"; npx playwright test e2e/screenshots.spec.ts
 * Later tasks add their routes to ROUTES.
 */
const ROUTES: { name: string; hash: string; graph?: boolean }[] = [
  { name: "home", hash: "" },
  { name: "stage1", hash: "#/e/ev-setup/setup/1" },
  { name: "stage1-locked", hash: "#/e/ev-run/setup/1" },
  { name: "stage2", hash: "#/e/ev-setup/setup/2" },
  { name: "stage2-advanced", hash: "#/e/ev-adv/setup/2" },
  { name: "stage2-locked", hash: "#/e/ev-run/setup/2" },
  { name: "stage3", hash: "#/e/ev-odd/setup/3" },
  { name: "stage3-locked", hash: "#/e/ev-run/setup/3" },
  { name: "pass", hash: "#/e/ev-run/pass" },
  { name: "pass-complete", hash: "#/e/ev-done/pass" },
  { name: "match-new", hash: "#/e/ev-run/pass/match/0" },
  { name: "match-saved", hash: "#/e/ev-done/pass/match/1" },
  { name: "match-chart", hash: "#/e/ev-chart/pass/match/1", graph: true },
  { name: "calculator", hash: "#/calculator" },
  { name: "about", hash: "#/about" },
  { name: "not-found", hash: "#/e/missing/pass" },
];
const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
];
const SCHEMES = ["light", "dark"] as const;
const dir = process.env.SCREENSHOT_DIR;

for (const route of ROUTES) {
  for (const viewport of VIEWPORTS) {
    for (const scheme of SCHEMES) {
      test(`screenshot ${route.name} ${viewport.name} ${scheme}`, async ({ page }) => {
        test.skip(!dir, "set SCREENSHOT_DIR to take review screenshots");
        test.setTimeout(240_000);
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.emulateMedia({ colorScheme: scheme });
        await page.goto("./");
        await seed(page, {
          events: [
            fixtureDoc("apply_stage1", { id: "ev-setup", name: "Club night 3 Oct" }),
            fixtureDoc("start_event", { id: "ev-run", name: "League round 2" }),
            fixtureDoc("apply_stage1", { id: "ev-adv", name: "Mixed targets" }, "advanced"),
            fixtureDoc("redraw", { id: "ev-odd", name: "Five archers" }, "byes_sat_out"),
            fixtureDoc("record_match@-1", { id: "ev-done", name: "Finished night" }),
            fixtureDoc("record_match@4", { id: "ev-chart", name: "Chart night" }),
          ],
        });
        await page.goto(`./${route.hash}`);
        await page
          .getByText("Getting the scoring engine ready")
          .waitFor({ state: "detached", timeout: 200_000 });
        if (route.graph) {
          await page.getByRole("switch", { name: "Graph view" }).check();
          await page.getByRole("checkbox", { name: "Show previous passes' scores too" }).check();
          await page.getByTestId("pair-chart").waitFor();
        }
        await page.screenshot({
          path: `${dir}/${route.name}-${viewport.name}-${scheme}.png`,
          fullPage: true,
        });
      });
    }
  }
}
