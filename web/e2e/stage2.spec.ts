import { expect, test, type Page } from "@playwright/test";
import { fixtureDoc, readStored, seed } from "./seed";

/**
 * UI-12: Stage 2 through the real engine, on one shared page (serial); each test seeds its event.
 */

const SIMPLE = fixtureDoc("apply_stage1", { id: "ev-simple", name: "Club night" });
const ADVANCED = fixtureDoc("apply_stage1", { id: "ev-adv", name: "Mixed targets" }, "advanced");
const ARCHERS = [
  { name: "Ann", bowstyle: "Recurve", handicap: "35" },
  { name: "Ben", bowstyle: "Compound", handicap: "20" },
  { name: "Cat", bowstyle: "Barebow", handicap: "50" },
  { name: "Dan", bowstyle: "Recurve", handicap: "35" },
];

test.describe.configure({ mode: "serial" });
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("./");
});

test.afterAll(async () => {
  await page.close();
});

/**
 * Seed one event and open Stage 2 once its lists have loaded (they come from the engine).
 *
 * @param doc - The event document at stage 1.
 */
async function openStage2(doc: Record<string, unknown>) {
  await page.goto("./");
  await seed(page, { events: [doc] });
  await page.goto(`./#/e/${doc.id as string}/setup/2`);
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled({ timeout: 240_000 });
}

const input = (label: string, row: number) => page.getByLabel(`${label}, archer ${row}`);

/**
 * Choose an option in one of an archer's selects.
 *
 * @param label - The column, e.g. "Bowstyle".
 * @param row - The archer (1-based).
 * @param option - The option's text.
 */
async function choose(label: string, row: number, option: string) {
  await page.getByRole("combobox", { name: `${label}, archer ${row}` }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

/**
 * Type the archers into the table.
 *
 * @param archers - Name, bowstyle and handicap per row.
 */
async function typeArchers(archers: typeof ARCHERS) {
  for (const [i, archer] of archers.entries()) {
    await input("Name", i + 1).fill(archer.name);
    await choose("Bowstyle", i + 1, archer.bowstyle);
    await input("Handicap", i + 1).fill(archer.handicap);
  }
}

test("a rejected submit keeps every typed value and highlights the row the bridge names", async () => {
  await openStage2(SIMPLE);
  await typeArchers([ARCHERS[0], ARCHERS[1], { ...ARCHERS[2], handicap: "200" }, ARCHERS[3]]);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("stage2-error")).toContainText(
    /^Please check the archersRow 3: handicap must be between 0(\.0)? and 150(\.0)?, got 200\.$/,
  );
  await expect(page).toHaveURL(/setup\/2$/);
  for (const [i, archer] of ARCHERS.entries()) {
    await expect(input("Name", i + 1)).toHaveValue(archer.name);
    await expect(page.getByRole("combobox", { name: `Bowstyle, archer ${i + 1}` })).toHaveValue(
      archer.bowstyle,
    );
    await expect(input("Handicap", i + 1)).toHaveValue(i === 2 ? "200" : archer.handicap);
  }
  const rows = page.getByTestId("archer-table").locator("tbody tr");
  await expect(rows.nth(2)).toHaveAttribute("data-invalid", "true");
  await expect(rows.nth(0)).not.toHaveAttribute("data-invalid");
  await expect(input("Handicap", 3)).toHaveAttribute("aria-invalid", "true");
});

test("Enter in a name moves to the next row's name", async () => {
  await openStage2(SIMPLE);
  await input("Name", 1).fill("Ann");
  await input("Name", 1).press("Enter");
  await expect(input("Name", 2)).toBeFocused();
  await expect(page).toHaveURL(/setup\/2$/);
});

test("in Advanced mode, an archer without a face type, face size or distance is rejected", async () => {
  await openStage2(ADVANCED);
  await expect(page.getByRole("columnheader", { name: "Face type" })).toBeVisible();
  await typeArchers(ARCHERS);
  for (const [column, row] of [
    ["Face type", 2],
    ["Face size", 3],
    ["Distance", 4],
  ] as const) {
    // Clicking the selected option clears the field.
    const box = page.getByRole("combobox", { name: `${column}, archer ${row}` });
    const chosen = await box.inputValue();
    await box.click();
    await page.getByRole("option", { name: chosen, exact: true }).click();
    await expect(box).toHaveValue("");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByTestId("stage2-error")).toContainText(`Row ${row}:`);
    await expect(
      page
        .getByTestId("archer-table")
        .locator("tbody tr")
        .nth(row - 1),
    ).toHaveAttribute("data-invalid", "true");
    await expect(page).toHaveURL(/setup\/2$/);
    await box.click();
    await page.getByRole("option", { name: chosen, exact: true }).click();
  }
});

test("Lookback and Start weight appear only when updating is Yes, in Advanced mode", async () => {
  await openStage2(SIMPLE);
  await expect(page.getByTestId("update-handicaps")).toHaveCount(0);
  await openStage2(ADVANCED);
  await expect(page.getByLabel("Lookback (passes)")).toHaveCount(0);
  await page.getByTestId("update-handicaps").getByText("Yes").click();
  await expect(page.getByLabel("Lookback (passes)")).toHaveValue("4");
  // The default start weight is the number of passes per archer (18 arrows / 6 per pass).
  await expect(page.getByLabel("Start weight (passes)")).toHaveValue("3");
  await page.getByTestId("update-handicaps").getByText("No").click();
  await expect(page.getByLabel("Start weight (passes)")).toHaveCount(0);
});

test("archers are cards at 390 px wide and a table at 1440 px", async () => {
  await openStage2(SIMPLE);
  await expect(page.getByTestId("archer-table")).toBeVisible();
  await expect(page.getByTestId("archer-cards")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("archer-cards")).toBeVisible();
  await expect(page.getByTestId("archer-table")).toHaveCount(0);
  await expect(page.getByTestId("archer-cards").getByText("Archer 4")).toBeVisible();
  await expect(page.getByTestId("archer-cards").getByLabel("Name")).toHaveCount(4);
  await page.setViewportSize({ width: 1440, height: 900 });
});

test("typed values survive a reload (draft restored)", async () => {
  await openStage2(SIMPLE);
  await typeArchers(ARCHERS.slice(0, 2));
  await expect
    .poll(
      async () => {
        const draft = (await readStored(page, "draft:ev-simple")) as
          { stage2?: { rows: unknown[] } } | undefined;
        return draft?.stage2?.rows.slice(0, 2);
      },
      { timeout: 5000 },
    )
    .toMatchObject([{ name: "Ann" }, { name: "Ben", handicap: 20 }]);
  await page.reload();
  await expect(input("Name", 2)).toHaveValue("Ben");
  await expect(page.getByRole("combobox", { name: "Bowstyle, archer 2" })).toHaveValue("Compound");
  await expect(input("Handicap", 1)).toHaveValue("35");
});

test("the calculator drawer opens from Stage 2 and closing it keeps the typed archers", async () => {
  await openStage2(SIMPLE);
  await typeArchers(ARCHERS.slice(0, 1));
  await page.getByRole("button", { name: "Handicap calculator" }).click();
  const drawer = page.getByRole("dialog", { name: "Handicap calculator" });
  await drawer.getByLabel("Full round score").fill("550");
  await drawer.getByRole("button", { name: "Calculate" }).click();
  await expect(drawer.getByTestId("calculator-result")).toHaveText("Handicap: 41.4");
  await expect(page).toHaveURL(/setup\/2$/);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(input("Name", 1)).toHaveValue("Ann");
  await expect(input("Handicap", 1)).toHaveValue("35");
  await expect(page.getByTestId("stage2-error")).toHaveCount(0);
});

test("a valid submit stores the archers, discards the draft and opens Stage 3", async () => {
  await openStage2(SIMPLE);
  await typeArchers(ARCHERS);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/#\/e\/ev-simple\/setup\/3$/);
  const stored = (await readStored(page, "event:ev-simple")) as {
    setup: { stage: number };
    archers: { name: string; handicap: number }[];
    assignment: number[];
  };
  expect(stored.setup.stage).toBe(2);
  expect(stored.archers.map((a) => [a.name, a.handicap])).toEqual([
    ["Ann", 35],
    ["Ben", 20],
    ["Cat", 50],
    ["Dan", 35],
  ]);
  expect([...stored.assignment].sort()).toEqual([0, 1, 2, 3]);
  expect(await readStored(page, "draft:ev-simple")).toBeUndefined();
});
