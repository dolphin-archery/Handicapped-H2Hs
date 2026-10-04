import { expect, test, type Page } from "@playwright/test";
import { fixtureDoc, readStored, seed } from "./seed";

/**
 * UI-11: Stage 1 through the real engine. One page is shared (serial) so the engine's downloads
 * stay in the browser cache; each test seeds its own event.
 */

const NEW = fixtureDoc("new_document", { id: "ev-new", name: "Club night" });
const STAGE2 = fixtureDoc("apply_stage2", { id: "ev-s2", name: "Archers entered" });
const RUNNING = fixtureDoc("start_event", { id: "ev-run", name: "League round" });

test.describe.configure({ mode: "serial" });
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await page.goto("./");
});

test.afterAll(async () => {
  await page.close();
});

/**
 * Seed one event and open its Stage 1, waiting until the engine's lists have loaded.
 *
 * @param doc - The event document.
 */
async function openStage1(doc: Record<string, unknown>) {
  await page.goto("./");
  await seed(page, { events: [doc] });
  await page.goto(`./#/e/${doc.id as string}/setup/1`);
  await expect(page.getByRole("heading", { name: "Stage 1" })).toBeVisible();
}

/** Wait for the engine (the distance list comes from `options`). */
async function engineReady() {
  await expect(page.getByRole("combobox", { name: "Distance" })).toBeEnabled({ timeout: 240_000 });
}

const nPass = () => page.getByTestId("n-pass-value");
const slider = () => page.getByRole("slider");

test("arrows per pass offers only divisors, remembers the choice and snaps to the nearest", async () => {
  await openStage1(NEW);
  await expect(nPass()).toHaveText("12");
  // 60 has 12 divisors: 1 2 3 4 5 6 10 12 15 20 30 60. Move one step right: 15.
  await slider().focus();
  await page.keyboard.press("ArrowRight");
  await expect(nPass()).toHaveText("15");
  await page.keyboard.press("ArrowLeft");
  await expect(nPass()).toHaveText("12");
  await expect(slider()).toHaveAttribute("aria-valuemax", "11");

  // 50: divisors 1 2 5 10 25 50; 10 is nearest to the remembered 12.
  await page.getByLabel("Total arrows").fill("50");
  await expect(nPass()).toHaveText("10");
  await expect(slider()).toHaveAttribute("aria-valuemax", "5");
  // Typing 48 digit by digit passes through 4 (shows 4) and then returns to the remembered 12.
  await page.getByLabel("Total arrows").fill("4");
  await expect(nPass()).toHaveText("4");
  await page.getByLabel("Total arrows").fill("48");
  await expect(nPass()).toHaveText("12");
});

test("Shoot byes? is shown only for an odd number of archers of 3 or more", async () => {
  await openStage1(NEW);
  const byes = page.getByText("Shoot byes?");
  for (const [n, shown] of [
    ["4", false],
    ["3", true],
    ["2", false],
    ["5", true],
    ["1", false],
    ["8", false],
  ] as const) {
    await page.getByLabel("Number of archers").fill(n);
    await expect(byes).toHaveCount(shown ? 1 : 0);
  }
});

test("Simple mode shows distance (20 yd, grouped) and face size (60 cm); Advanced hides them", async () => {
  await openStage1(NEW);
  await engineReady();
  await expect(page.getByRole("combobox", { name: "Distance" })).toHaveValue("20 yd");
  await expect(page.getByRole("combobox", { name: "Face size" })).toHaveValue("60 cm");
  await page.getByRole("combobox", { name: "Distance" }).click();
  await expect(page.getByRole("group", { name: "Metric" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Imperial" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByText("Advanced", { exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Distance" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Face size" })).toHaveCount(0);
  await expect(page.getByTestId("advanced-note")).toBeVisible();
});

test("typed values survive a reload before submit", async () => {
  await openStage1(NEW);
  await page.getByLabel("Number of archers").fill("7");
  await page.getByLabel("Total arrows").fill("72");
  await page.getByText("No", { exact: true }).click();
  await expect
    .poll(async () => (await readStored(page, "draft:ev-new")) as unknown, { timeout: 5000 })
    .toMatchObject({ stage1: { n_archers: 7, total_arrows: 72, shoot_byes: false } });
  await page.reload();
  await expect(page.getByLabel("Number of archers")).toHaveValue("7");
  await expect(page.getByLabel("Total arrows")).toHaveValue("72");
  await expect(nPass()).toHaveText("12");
  await expect(page.getByTestId("shoot-byes").getByRole("radio", { name: "No" })).toBeChecked();
});

test("invalid input shows the bridge's apply_stage1 messages", async () => {
  await openStage1(NEW);
  await engineReady();
  await page.getByLabel("Number of archers").fill("1");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("stage1-error")).toContainText("Need at least 2 archers, got 1.");
  await page.getByLabel("Number of archers").fill("4");
  await page.getByLabel("Total arrows").fill("0");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("stage1-error")).toContainText(
    "Arrows per pass (1) must evenly divide total arrows (0).",
  );
  await expect(page).toHaveURL(/setup\/1$/);
});

test("a valid submit stores the document, discards the draft and opens Stage 2", async () => {
  await openStage1(NEW);
  await engineReady();
  await page.getByLabel("Number of archers").fill("5");
  await page.getByLabel("Total arrows").fill("36");
  await page.getByRole("combobox", { name: "Distance" }).click();
  await page.getByRole("option", { name: "18 m" }).click();
  await page.getByRole("combobox", { name: "Face size" }).click();
  await page.getByRole("option", { name: "40 cm" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/#\/e\/ev-new\/setup\/2$/);
  const stored = (await readStored(page, "event:ev-new")) as { setup: Record<string, unknown> };
  expect(stored.setup).toMatchObject({
    stage: 1,
    n_archers: 5,
    total_arrows: 36,
    n_pass: 12,
    setup_mode: "simple",
    shoot_byes: true,
    target: { distance_key: "18m", face_cm: 40 },
  });
  expect(await readStored(page, "draft:ev-new")).toBeUndefined();
});

test("changing Stage 1 after Stage 2 asks first and keeps the archers as Stage 2's draft", async () => {
  await openStage1(STAGE2);
  await engineReady();
  // Unchanged: Continue moves on without clearing anything.
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/setup\/2$/);
  expect(((await readStored(page, "event:ev-s2")) as { archers: unknown[] }).archers).toHaveLength(
    4,
  );

  await page.goto("./#/e/ev-s2/setup/1");
  await page.getByLabel("Total arrows").fill("48");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("dialog")).toContainText("clears the pairings and the archers");
  await page.getByRole("button", { name: "Keep the current setup" }).click();
  await expect(page).toHaveURL(/setup\/1$/);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Change setup" }).click();
  await expect(page).toHaveURL(/setup\/2$/);
  const stored = (await readStored(page, "event:ev-s2")) as { archers: unknown[] };
  expect(stored.archers).toEqual([]);
  const draft = (await readStored(page, "draft:ev-s2")) as { stage2: { rows: unknown[] } };
  expect(draft.stage2.rows).toHaveLength(4);
});

test("after the start, Stage 1 is a read-only summary", async () => {
  await openStage1(RUNNING);
  await expect(page.getByTestId("setup-locked")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);
  await expect(page.getByLabel("Number of archers")).toHaveAttribute("readonly", "");
});
