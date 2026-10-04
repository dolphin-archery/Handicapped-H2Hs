import { expect, test, type Page } from "@playwright/test";
import { fixtureDoc, readStored, seed } from "./seed";

/**
 * UI-13: Stage 3 through the real engine, on one shared page (serial); each test seeds its event.
 */

const SIMPLE = fixtureDoc("apply_stage2", { id: "ev-s3", name: "Club night" });
const BYES_SHOT = fixtureDoc("redraw", { id: "ev-shot", name: "Byes shot" }, "byes_shot");
const BYES_SAT = fixtureDoc("redraw", { id: "ev-sat", name: "Byes sat out" }, "byes_sat_out");

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
 * Seed one event and open Stage 3 once the pairings have loaded (they come from the engine).
 *
 * @param doc - The event document at stage 2.
 */
async function openStage3(doc: Record<string, unknown>) {
  await page.goto("./");
  await seed(page, { events: [doc] });
  await page.goto(`./#/e/${doc.id as string}/setup/3`);
  await expect(table()).toBeVisible({ timeout: 240_000 });
}

const table = () => page.getByTestId("pairings-table");
const stored = async (id: string) =>
  (await readStored(page, `event:${id}`)) as { status: string; assignment: number[] };

test("Redraw changes the pairings and stores the new draw", async () => {
  await openStage3(SIMPLE);
  const before = (await table().textContent()) ?? "";
  const assignment = (await stored("ev-s3")).assignment;
  await page.getByRole("button", { name: "Redraw pairings" }).click();
  await expect(table()).not.toHaveText(before);
  await expect.poll(async () => (await stored("ev-s3")).assignment).not.toEqual(assignment);
  await expect(page).toHaveURL(/setup\/3$/);
});

test("the displayed draw is identical after a reload", async () => {
  await openStage3(SIMPLE);
  await page.getByRole("button", { name: "Redraw pairings" }).click();
  await expect(page.getByRole("button", { name: "Redraw pairings" })).toBeEnabled();
  const shown = (await table().textContent()) ?? "";
  await page.reload();
  await expect(table()).toHaveText(shown, { timeout: 240_000 });
});

test("byes (shoots alone) and sitting-out archers are shown for an odd number of archers", async () => {
  await openStage3(BYES_SHOT);
  const rows = table().locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Ben vs Eve");
  await expect(rows.nth(0)).toContainText("Ann (bye - shoots alone)");
  await expect(rows.nth(0).locator("td").nth(2)).toHaveText("-");

  await openStage3(BYES_SAT);
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(2).locator("td").nth(1)).toHaveText("Ann vs Cat");
  await expect(rows.nth(2).locator("td").nth(2)).toHaveText("Ben, Dan, Eve");
});

test("Back to Stage 2 is available before confirmation", async () => {
  await openStage3(SIMPLE);
  await page.getByRole("link", { name: "Back to Stage 2" }).click();
  await expect(page).toHaveURL(/setup\/2$/);
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
});

test("Confirm starts the event, opens the pass overview and locks Stages 1 to 3", async () => {
  await openStage3(SIMPLE);
  const shown = (await table().textContent()) ?? "";
  await page.getByRole("button", { name: "Confirm pairings and start event" }).click();
  await expect(page).toHaveURL(/#\/e\/ev-s3\/pass$/);
  expect((await stored("ev-s3")).status).toBe("running");

  for (const stage of [1, 2, 3]) {
    await page.goto(`./#/e/ev-s3/setup/${stage}`);
    await expect(page.getByTestId("setup-locked")).toBeVisible({ timeout: 240_000 });
  }
  await expect(table()).toHaveText(shown);
  await expect(page.getByRole("button", { name: "Redraw pairings" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Confirm pairings/ })).toHaveCount(0);
  await page.goto("./#/e/ev-s3/setup/2");
  await expect(page.getByLabel("Name, archer 1")).toHaveAttribute("readonly", "");
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);
  await page.goto("./#/e/ev-s3/setup/1");
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);
});
