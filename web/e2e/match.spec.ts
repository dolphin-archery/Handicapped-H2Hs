import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { fixtureDoc, fixtureSteps, readStored, seed } from "./seed";

/**
 * UI-15: the match view through the real engine, on one shared page (serial). The tie-break
 * scenarios are those of tests/test_event_routes.py ("Tie-break tick boxes on the match page"),
 * with the tie_break fixture's two archers of equal handicap (Ben is position 0, Ann position 1).
 */

type Doc = Record<string, unknown> & {
  archers: { name: string }[];
  assignment: number[];
};

const TIED = fixtureDoc("start_event", { id: "ev-m" }, "tie_break") as Doc;
const TIEBREAK_MESSAGE =
  "Percentile and score are tied. Tick which archer's arrow was closest to the middle, then save again.";
const DECIDED_NOTE = "Percentile and score were tied; decided by closest to the middle.";

test.describe.configure({ mode: "serial", timeout: 240_000 });
let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
  await page.goto("./");
});

test.afterAll(async () => {
  await context.close();
});

/**
 * Seed the event and open one match of its current pass once it has loaded.
 *
 * @param doc - The event document.
 * @param index - The match index.
 * @param target - The page to use (default: the shared page).
 */
async function openMatch(doc: Doc, index: number, target: Page = page) {
  await target.goto("./");
  await seed(target, { events: [doc] });
  await target.goto(`./#/e/${doc.id as string}/pass/match/${index}`);
  await expect(target.getByRole("button", { name: /^Save/ })).toBeVisible({ timeout: 240_000 });
}

/**
 * Type scores into the boxes, by schedule position.
 *
 * @param doc - The event document (for the names).
 * @param scores - Position (text) -> score.
 */
async function fillScores(doc: Doc, scores: Record<string, number | string>) {
  for (const [position, score] of Object.entries(scores)) {
    const name = doc.archers[doc.assignment[Number(position)]].name;
    await page.getByLabel(new RegExp(`^${name} score \\(0-\\d+\\)$`)).fill(String(score));
  }
}

const save = () => page.getByRole("button", { name: /^Save (changed )?scores$/ }).click();
const tiebreak = () => page.getByTestId("tiebreak");
const stored = async (id = "ev-m") =>
  (await readStored(page, `event:${id}`)) as {
    status: string;
    scores: Record<
      string,
      Record<string, { scores: Record<string, number>; closest: number | null }>
    >;
  };
const winners = async () =>
  page.getByTestId("pass-table").locator("tbody tr td:last-child").allTextContents();

test.describe("tie-break (test_event_routes.py scenarios)", () => {
  test("a normal match has no tie-break control, fresh or saved by score", async () => {
    await openMatch(TIED, 0);
    await expect(tiebreak()).toHaveCount(0);
    await fillScores(TIED, { "0": 100, "1": 60 });
    await save();
    await expect(page.getByTestId("match-saved")).toBeVisible();
    await expect(tiebreak()).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("button", { name: "Save changed scores" })).toBeVisible();
    await expect(tiebreak()).toHaveCount(0);
  });

  test("a tie without a choice is refused, the typed scores are kept and the control appears", async () => {
    await openMatch(TIED, 0);
    await fillScores(TIED, { "0": 90, "1": 90 });
    await save();
    await expect(page.getByTestId("match-error")).toHaveText(TIEBREAK_MESSAGE);
    await expect(page.getByLabel(/^Ben score/)).toHaveValue("90");
    await expect(page.getByLabel(/^Ann score/)).toHaveValue("90");
    await expect(tiebreak()).toContainText("The percentile and the score are tied");
    await expect(tiebreak().getByRole("radio")).toHaveCount(2);
    await expect(tiebreak().getByRole("radio", { checked: true })).toHaveCount(0);
    expect((await stored()).scores).toEqual({});
  });

  test("a tie with a choice is saved for the chosen archer, says why, and reopens with it chosen", async () => {
    await openMatch(TIED, 0);
    await fillScores(TIED, { "0": 90, "1": 90 });
    await save();
    await tiebreak().getByRole("radio", { name: "Ann" }).check();
    await save();
    await expect(page.getByTestId("match-saved")).toBeVisible();
    expect(await winners()).toEqual(["No", "Yes"]);
    await expect(page.getByText(DECIDED_NOTE)).toBeVisible();
    await page.reload();
    await expect(tiebreak().getByRole("radio", { name: "Ann" })).toBeChecked();
    await expect(tiebreak().getByRole("radio", { name: "Ben" })).not.toBeChecked();
    await page.getByRole("link", { name: "Back to overview" }).first().click();
    await expect(page.getByTestId("overview-table").locator("tbody tr td").nth(3)).toHaveText(
      "Ann",
    );
  });

  test("editing a closest-decided match to untied scores drops the note and the control", async () => {
    await openMatch(TIED, 0);
    await fillScores(TIED, { "0": 90, "1": 90 });
    await save();
    await tiebreak().getByRole("radio", { name: "Ben" }).check();
    await save();
    await expect(page.getByText(DECIDED_NOTE)).toBeVisible();
    await fillScores(TIED, { "0": 90, "1": 95 });
    await save();
    await expect(page.getByTestId("match-saved")).toBeVisible();
    expect(await winners()).toEqual(["No", "Yes"]);
    await expect(page.getByText(DECIDED_NOTE)).toHaveCount(0);
    await expect(tiebreak()).toHaveCount(0);
  });

  test("a refused re-save into a tie keeps the saved result and shows the control", async () => {
    await openMatch(TIED, 0);
    await fillScores(TIED, { "0": 100, "1": 60 });
    await save();
    await expect(page.getByTestId("match-saved")).toBeVisible();
    await expect(tiebreak()).toHaveCount(0);
    await fillScores(TIED, { "0": 90, "1": 90 });
    await save();
    await expect(page.getByTestId("match-error")).toHaveText(TIEBREAK_MESSAGE);
    await expect(tiebreak()).toBeVisible();
    expect((await stored()).scores["0"]["0"].scores).toEqual({ "0": 100, "1": 60 });
  });
});

test("scores outside 0 to the maximum, or not whole numbers, get the bridge's message", async () => {
  await openMatch(TIED, 0);
  await fillScores(TIED, { "0": 999, "1": 60 });
  await save();
  await expect(page.getByTestId("match-error")).toContainText("Score must be between 0 and 120");
  await fillScores(TIED, { "0": "90.5" });
  await save();
  await expect(page.getByTestId("match-error")).toHaveText(
    "Score must be a whole number, got 90.5.",
  );
  expect((await stored()).scores).toEqual({});
});

test("no handicap is shown beside the archers' names while entering scores", async () => {
  await openMatch(TIED, 0);
  const labels = await page.locator("form label").allTextContents();
  expect(labels).toEqual(["Ben score (0-120)", "Ann score (0-120)"]);
  await expect(page.locator("form").getByText(/handicap/i)).toHaveCount(0);
});

test("a bye match shows one input, no winner and no chart panel", async () => {
  const doc = fixtureDoc("start_event", { id: "ev-bye" }, "byes_shot") as Doc;
  await openMatch(doc, 2);
  await expect(page.getByRole("heading", { name: "Ann - bye, no opponent" })).toBeVisible();
  await expect(page.locator("form input")).toHaveCount(1);
  await page.getByLabel(/^Ann score/).fill("100");
  await save();
  await expect(page.getByTestId("match-saved")).toBeVisible();
  expect(await winners()).toEqual(["-"]);
  await expect(page.getByTestId("chart-column")).toHaveCount(0);
  await expect(page.getByTestId("graph-view-off")).toHaveCount(0);
  await page.getByRole("switch", { name: "Graph view" }).check();
  await expect(page.getByTestId("chart-panel")).toHaveCount(0);
  await page.getByRole("switch", { name: "Graph view" }).uncheck();
});

test("reloading mid-entry restores the typed scores from the draft", async () => {
  await openMatch(TIED, 0);
  await fillScores(TIED, { "0": 77 });
  await expect
    .poll(async () => readStored(page, "draft:ev-m"), { timeout: 5000 })
    .toMatchObject({ "match:0:0": { scores: { "0": 77 } } });
  await page.reload();
  await expect(page.getByLabel(/^Ben score/)).toHaveValue("77", { timeout: 240_000 });
});

test("saved scores survive closing and reopening the tab", async () => {
  await openMatch(TIED, 0);
  await fillScores(TIED, { "0": 101, "1": 64 });
  await save();
  await expect(page.getByTestId("match-saved")).toBeVisible();
  await page.close();
  page = await context.newPage();
  await page.goto("./#/e/ev-m/pass/match/0");
  await expect(page.getByLabel(/^Ben score/)).toHaveValue("101", { timeout: 240_000 });
  await expect(page.getByLabel(/^Ann score/)).toHaveValue("64");
});

test("saving the last match of the final pass stores status complete; Home shows Complete", async () => {
  const doc = fixtureDoc("record_match@5", { id: "ev-last", name: "Last match" }) as Doc;
  const last = fixtureSteps("simple", "record_match").at(-1)!;
  await openMatch(doc, last.payload.match_index as number);
  await fillScores(doc, last.payload.scores as Record<string, number>);
  await save();
  await expect(page.getByTestId("match-saved")).toBeVisible();
  expect((await stored("ev-last")).status).toBe("complete");
  await page.goto("./#/");
  await expect(page.getByTestId("event-card")).toContainText("Complete");
});

test("after the event is complete, a final-pass match can still be edited and saved", async () => {
  const doc = fixtureDoc("record_match@-1", { id: "ev-done" }) as Doc;
  await openMatch(doc, 0);
  await expect(page.getByRole("button", { name: "Save changed scores" })).toBeVisible();
  await fillScores(doc, { "0": 100, "1": 108 });
  await save();
  await expect(page.getByTestId("match-saved")).toBeVisible();
  const after = await stored("ev-done");
  expect(after.status).toBe("complete");
  expect(after.scores["2"]["0"].scores).toEqual({ "0": 100, "1": 108 });
});

test("the This pass table shows the bridge's match rows exactly; Next unscored and Back appear", async () => {
  const doc = fixtureDoc("start_event", { id: "ev-s" }) as Doc;
  const first = fixtureSteps("simple", "record_match")[0];
  await openMatch(doc, 0);
  await fillScores(doc, first.payload.scores as Record<string, number>);
  await save();
  const rows = (first.result.data!.match as { rows: Record<string, string>[] }).rows;
  const shown = page.getByTestId("pass-table").locator("tbody tr");
  await expect(shown).toHaveCount(rows.length);
  for (const [i, row] of rows.entries()) {
    await expect(shown.nth(i).locator("td")).toHaveText([
      row.archer,
      row.score,
      row.percentile,
      row.handicap,
      row.winner,
    ]);
  }
  await page.getByRole("link", { name: "Next unscored match" }).click();
  await expect(page).toHaveURL(/pass\/match\/1$/);
  await expect(page.getByRole("button", { name: "Save scores" })).toBeVisible();
});
