import { test } from "@playwright/test";
import { openRoute, ROUTES } from "./routes";

/**
 * Review screenshots (UILoopPrompt step 4): each route of e2e/routes.ts at the UISpec 7.4 widths,
 * light and dark. Skipped unless SCREENSHOT_DIR is set, and only on the chromium project, e.g.
 *   $env:SCREENSHOT_DIR = "C:\temp\shots"; npx playwright test e2e/screenshots.spec.ts
 * SCREENSHOT_ONLY narrows the routes by name (a regular expression).
 */
const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1280, height: 720 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "phone", width: 390, height: 844 },
];
const SCHEMES = ["light", "dark"] as const;
const dir = process.env.SCREENSHOT_DIR;
const only = new RegExp(process.env.SCREENSHOT_ONLY ?? "");

for (const route of ROUTES.filter((r) => only.test(r.name))) {
  for (const viewport of VIEWPORTS) {
    for (const scheme of SCHEMES) {
      test(`screenshot ${route.name} ${viewport.name} ${scheme}`, async ({ page }, info) => {
        test.skip(!dir || info.project.name !== "chromium", "set SCREENSHOT_DIR (chromium only)");
        test.setTimeout(240_000);
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.emulateMedia({ colorScheme: scheme });
        await openRoute(page, route);
        await page.screenshot({
          path: `${dir}/${route.name}-${viewport.name}-${scheme}.png`,
          fullPage: true,
        });
      });
    }
  }
}
