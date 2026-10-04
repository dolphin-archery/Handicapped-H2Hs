import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { fixtureDoc, readStored, seed } from "./seed";

/**
 * UI-14: the current pass overview through the real engine, on one shared page (serial). Documents
 * come from the "simple" fixture (4 archers, 3 passes of 2 matches).
 */

const STARTED = fixtureDoc("start_event", { id: "ev-p" });
const PARTIAL = fixtureDoc("record_match@0", { id: "ev-p" }); // pass 1, one match scored
const PASS1_DONE = fixtureDoc("record_match@1", { id: "ev-p" });
const COMPLETE = fixtureDoc("record_match@-1", { id: "ev-p", name: "Finished night" });
const FINAL_OVERVIEW = (
  JSON.parse(
    readFileSync(
      path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        "../../tests/fixtures/bridge/simple.json",
      ),
      "utf8",
    ),
  ) as { steps: { command: string; result: { data: Record<string, unknown> } }[] }
).steps
  .filter((s) => s.command === "overview")
  .at(-1)!.result.data as {
  matches: { names: string[]; score: string; percentiles: string; winner: string }[];
};

test.describe.configure({ mode: "serial", timeout: 240_000 });
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await page.goto("./");
});

test.afterAll(async () => {
  await page.close();
});

/**
 * Seed the event and open the current pass once the overview has loaded.
 *
 * @param doc - The event document.
 */
async function openPass(doc: Record<string, unknown>) {
  await page.goto("./");
  await seed(page, { events: [doc] });
  await page.goto("./#/e/ev-p/pass");
  await expect(page.getByTestId("overview-table")).toBeVisible({ timeout: 240_000 });
}

const advance = () => page.getByRole("button", { name: "Advance to next pass" });

test("Advance is disabled, with the reason, until every match in the pass is scored", async () => {
  await openPass(STARTED);
  await expect(page.getByRole("heading", { name: "Pass 1 of 3" })).toBeVisible();
  await expect(page.getByTestId("scored-count")).toHaveText("0 of 2 matches scored");
  await expect(advance()).toBeDisabled();
  await expect(page.getByTestId("advance-hint")).toHaveText(
    "Enter scores for every match in this pass first.",
  );
  await openPass(PARTIAL);
  await expect(page.getByTestId("scored-count")).toHaveText("1 of 2 matches scored");
  await expect(advance()).toBeDisabled();
  await openPass(PASS1_DONE);
  await expect(advance()).toBeEnabled();
  await expect(page.getByTestId("advance-hint")).toHaveCount(0);
});

test("Advance asks first: cancelling stays, confirming moves to the next pass and stores it", async () => {
  await openPass(PASS1_DONE);
  await advance().click();
  await expect(page.getByRole("dialog")).toContainText("Advance to pass 2?");
  await page.getByRole("button", { name: "Stay on this pass" }).click();
  await expect(page.getByRole("heading", { name: "Pass 1 of 3" })).toBeVisible();
  expect(((await readStored(page, "event:ev-p")) as { current_pass: number }).current_pass).toBe(0);

  await advance().click();
  await page.getByRole("dialog").getByRole("button", { name: "Advance" }).click();
  await expect(page.getByRole("heading", { name: "Pass 2 of 3" })).toBeVisible();
  await expect(page.getByTestId("scored-count")).toHaveText("0 of 2 matches scored");
  expect(((await readStored(page, "event:ev-p")) as { current_pass: number }).current_pass).toBe(1);
});

test("the final, complete pass shows the completion alert instead of Advance", async () => {
  await openPass(COMPLETE);
  const done = page.getByTestId("completion");
  await expect(done).toBeVisible();
  await expect(done.getByRole("link", { name: "View results" })).toBeVisible();
  await expect(done.getByRole("button", { name: "Download backup" })).toBeVisible();
  await expect(done).toContainText("saved only in this browser");
  for (const label of ["Leaderboard (CSV)", "Archer results (CSV)", "Full report (PDF)"]) {
    await expect(done.getByRole("button", { name: label })).toBeVisible();
  }
  await expect(advance()).toHaveCount(0);
});

test("a complete event is stored as complete and listed as Complete on Home", async () => {
  await openPass(COMPLETE);
  expect(((await readStored(page, "event:ev-p")) as { status: string }).status).toBe("complete");
  await page.goto("./#/");
  await expect(page.getByTestId("event-card")).toContainText("Complete");
});

test("Download backup in the completion alert downloads the event as JSON", async () => {
  await openPass(COMPLETE);
  const download = page.waitForEvent("download");
  await page.getByTestId("completion").getByRole("button", { name: "Download backup" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^backup_\d{8}-\d{6}\.json$/);
  const text = readFileSync(await file.path(), "utf8");
  expect(text).toContain('"Finished night"');
});

test("the table shows the bridge's overview values exactly", async () => {
  await openPass(COMPLETE);
  const rows = page.getByTestId("overview-table").locator("tbody tr");
  await expect(rows).toHaveCount(FINAL_OVERVIEW.matches.length);
  for (const [i, match] of FINAL_OVERVIEW.matches.entries()) {
    const cells = rows.nth(i).locator("td");
    await expect(cells.nth(0)).toHaveText(match.names.join(" vs "));
    await expect(cells.nth(1)).toHaveText(match.score);
    await expect(cells.nth(2)).toHaveText(match.percentiles);
    await expect(cells.nth(3)).toHaveText(match.winner);
    await expect(cells.nth(4)).toHaveText("Scored");
    await expect(cells.nth(5)).toHaveText("View / edit");
  }
});

test("clicking a row opens its match", async () => {
  await openPass(STARTED);
  await page.getByTestId("overview-table").locator("tbody tr").nth(1).locator("td").first().click();
  await expect(page).toHaveURL(/#\/e\/ev-p\/pass\/match\/1$/);
});
