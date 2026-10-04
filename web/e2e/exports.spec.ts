import { readFileSync } from "node:fs";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { pdfSummary } from "../tests/bridgeFixtures";
import { fixtureSteps, seed } from "./seed";

/**
 * UI-18: the three downloads through the real engine, from the Results view's Download menu and
 * from the final-pass completion alert (shared page, serial). The page's clock is fixed at the
 * fixtures' export time (2026-10-04 15:30:12 local), so file names and contents must equal the
 * recorded `export` outputs exactly; a PDF is compared through the fixtures' `pdfSummary` (its
 * header, page count and every line of text), since its bytes carry fpdf2's creation time.
 */

const steps = fixtureSteps("simple", "export");
const DOC: Record<string, unknown> = { ...(steps[0].payload.doc as object), id: "ev-x" };
const EXPECTED = Object.fromEntries(
  steps.map((step) => [step.payload.kind as string, step.result.data as Record<string, unknown>]),
);
const LABELS = {
  leaderboard_csv: "Leaderboard (CSV)",
  archer_results_csv: "Archer results (CSV)",
  results_pdf: "Full report (PDF)",
} as const;

test.describe.configure({ mode: "serial", timeout: 240_000 });
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.clock.setFixedTime(new Date(2026, 9, 4, 15, 30, 12));
  await page.goto("./");
  await seed(page, { events: [DOC] });
});

test.afterAll(async () => {
  await page.close();
});

/**
 * Click something that starts a download and check the file against the fixture.
 *
 * @param kind - The export kind.
 * @param start - Clicks the control that starts it.
 */
async function expectDownload(kind: keyof typeof LABELS, start: () => Promise<void>) {
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 200_000 }),
    start(),
  ]);
  const expected = EXPECTED[kind];
  expect(download.suggestedFilename()).toBe(expected.filename);
  const bytes = readFileSync(await download.path());
  if (kind === "results_pdf") {
    expect(bytes.subarray(0, 5).toString("latin1")).toBe("%PDF-");
    expect(pdfSummary(bytes.toString("base64"))).toEqual(expected.content);
  } else {
    expect(bytes.toString("utf-8")).toBe(expected.content);
  }
}

test("the fixture event is complete (status complete), as the completion alert needs", async () => {
  expect(DOC.status).toBe("complete");
});

for (const kind of Object.keys(LABELS) as (keyof typeof LABELS)[]) {
  test(`${kind} downloads from the Results view's Download menu`, async () => {
    await page.goto("./#/e/ev-x/results/leaderboard");
    const menu: Locator = page.getByRole("button", { name: "Download" });
    await expect(menu).toBeVisible({ timeout: 240_000 });
    await expectDownload(kind, async () => {
      await menu.click();
      await page.getByRole("menuitem", { name: LABELS[kind] }).click();
    });
  });

  test(`${kind} downloads from the completion alert`, async () => {
    await page.goto("./#/e/ev-x/pass");
    const alert = page.getByTestId("completion");
    await expect(alert).toBeVisible({ timeout: 240_000 });
    await expectDownload(kind, () => alert.getByRole("button", { name: LABELS[kind] }).click());
  });
}
