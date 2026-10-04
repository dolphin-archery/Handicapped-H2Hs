import { test } from "@playwright/test";

/**
 * Review screenshots (UILoopPrompt step 4): every listed route at 1440x900 and 390x844, in light
 * and dark mode. Skipped unless SCREENSHOT_DIR is set, e.g.
 *   $env:SCREENSHOT_DIR = "C:\\temp\\shots"; npx playwright test e2e/screenshots.spec.ts
 * Later tasks add their routes to ROUTES.
 */
const ROUTES: { name: string; hash: string }[] = [{ name: "home", hash: "" }];
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
        await page.goto(`./${route.hash}`);
        await page
          .getByTestId("engine-status")
          .and(page.locator("[data-state=ready]"))
          .waitFor({ timeout: 200_000 });
        await page.screenshot({
          path: `${dir}/${route.name}-${viewport.name}-${scheme}.png`,
          fullPage: true,
        });
      });
    }
  }
}
