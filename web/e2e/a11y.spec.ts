import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { openRoute, ROUTES } from "./routes";

/**
 * UI-19: accessibility and responsive checks on every route (UISpec.md 7.4 and 7.5), loaded once
 * per route and then resized and re-themed in place:
 * - the page title for the route;
 * - an axe scan with zero serious or critical violations, in light and dark;
 * - no horizontal page scroll at 1440, 1280, 768 and 390 px wide;
 * - at 390 px, tables of five or fewer columns fit without scrolling;
 * - every number field has a numeric `inputMode`, so phones show a number keypad;
 * - on the mobile project, interactive targets at least 44 px tall and inputs' font at least 16 px.
 */

test.describe.configure({ timeout: 240_000 });

const WIDTHS = [1440, 1280, 768, 390];
const SCHEMES = ["light", "dark"] as const;

/**
 * The axe violations of serious or critical impact, as short readable lines.
 *
 * @param page - The page.
 * @returns e.g. "color-contrast (3.2 #868e96 on #ffffff): <html snippet>".
 */
async function seriousViolations(page: Page): Promise<string[]> {
  const { violations } = await new AxeBuilder({ page }).analyze();
  return violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .flatMap((v) =>
      v.nodes.map((n) => {
        const data = n.any[0]?.data as {
          contrastRatio?: number;
          fgColor?: string;
          bgColor?: string;
        };
        const colours = data?.contrastRatio
          ? ` (${data.contrastRatio} ${data.fgColor} on ${data.bgColor})`
          : "";
        return `${v.id}${colours}: ${n.html.slice(0, 120)}`;
      }),
    );
}

/**
 * Whether the page scrolls sideways.
 *
 * @param page - The page.
 * @returns How many pixels wider the document is than the window (0 when it fits).
 */
const overflow = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/**
 * Visible tables with five or fewer columns that are wider than their scroll container.
 *
 * @param page - The page.
 * @returns A description of each table that does not fit.
 */
const narrowTablesThatScroll = (page: Page) =>
  page.evaluate(() =>
    Array.from(document.querySelectorAll("table"))
      .filter((table) => table.offsetParent !== null)
      .filter((table) => (table.tHead?.rows[0]?.cells.length ?? 99) <= 5)
      .filter((table) => {
        const box = table.parentElement!;
        return box.scrollWidth > box.clientWidth + 1;
      })
      .map((table) => `${table.dataset.testid ?? "table"}: ${table.parentElement!.scrollWidth}px`),
  );

/**
 * Visible interactive elements shorter than 44 px, and inputs whose font is under 16 px. A
 * checkbox, radio or switch is measured by its whole clickable label row; inline text links (in a
 * sentence) are exempt, as WCAG 2.5.8 allows.
 *
 * @param page - The page.
 * @returns A description of each element that is too small.
 */
const smallTargets = (page: Page) =>
  page.evaluate(() => {
    const problems: string[] = [];
    const describe = (el: Element) =>
      `${el.tagName.toLowerCase()} "${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30)}"`;
    const selector =
      "button, a[href], input:not([type=hidden]), select, textarea, [role=tab], [role=menuitem]";
    for (const el of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
      if (el.closest("[aria-hidden=true]")) continue;
      const style = getComputedStyle(el);
      if (el.tagName === "A" && style.display === "inline") continue;
      const toggle = el.matches("input[type=checkbox], input[type=radio]");
      const target = toggle
        ? (el.closest("label, .mantine-Checkbox-body, .mantine-Radio-body, .mantine-Switch-body") ??
          el)
        : el;
      const rect = target.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;
      if (getComputedStyle(target).visibility === "hidden") continue;
      if (rect.height < 44 - 0.5)
        problems.push(`${describe(el)} is ${rect.height.toFixed(1)}px tall`);
      if (el.matches("input:not([type=checkbox]):not([type=radio]), select, textarea")) {
        const size = parseFloat(style.fontSize);
        if (size < 16) problems.push(`${describe(el)} font ${size}px`);
      }
    }
    return problems;
  });

/**
 * Number fields without a numeric keypad hint.
 *
 * @param page - The page.
 * @returns The labels of number inputs whose `inputmode` is not "numeric" or "decimal".
 */
const numberFieldsWithoutKeypad = (page: Page) =>
  page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLInputElement>(".mantine-NumberInput-input"))
      .filter((input) => !["numeric", "decimal"].includes(input.inputMode))
      .map((input) => input.labels?.[0]?.textContent ?? input.name),
  );

for (const route of ROUTES) {
  test(`${route.name}: title, axe, no sideways scroll, compact tables, mobile targets`, async ({
    page,
    isMobile,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openRoute(page, route);
    await expect(page).toHaveTitle(
      route.title === "Handicapped H2Hs" ? route.title : `${route.title} - Handicapped H2Hs`,
    );

    expect(await numberFieldsWithoutKeypad(page), "inputMode").toEqual([]);

    for (const scheme of SCHEMES) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.waitForTimeout(200); // let the new colours settle before the scan
      expect(await seriousViolations(page), `axe in ${scheme}`).toEqual([]);
    }
    await page.emulateMedia({ colorScheme: "light" });

    if (isMobile) {
      expect(await overflow(page), "sideways scroll").toBeLessThanOrEqual(0);
      expect(await smallTargets(page)).toEqual([]);
      return;
    }
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await expect.poll(() => overflow(page), { message: `sideways scroll at ${width}px` }).toBe(0);
    }
    expect(await narrowTablesThatScroll(page), "tables at 390px").toEqual([]);
  });
}
