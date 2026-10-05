import { expect, test, type Locator, type Page } from "@playwright/test";
import type { ArcherResults, Results } from "../src/engine/types";
import { fixtureDoc, fixtureSteps, seed } from "./seed";

/**
 * UI-17: the Results tabs through the real engine, on one shared page (serial). Each scenario's
 * document is the one its fixture passed to `results`, so the expected values are the recorded
 * `results` and `archer_results` outputs.
 */

test.describe.configure({ mode: "serial", timeout: 240_000 });
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("./");
});

test.afterAll(async () => {
  await page.close();
});

/**
 * A scenario's document as passed to `results`, with the outputs recorded for it.
 *
 * @param scenario - The fixture's scenario.
 * @param id - The event id to store it under.
 * @returns The document and the expected `results` and `archer_results` data.
 */
function scenario(scenario: string, id: string) {
  const step = fixtureSteps(scenario, "results")[0];
  const archers = fixtureSteps(scenario, "archer_results")[0];
  return {
    doc: { ...(step.payload.doc as Record<string, unknown>), id },
    results: step.result.data as unknown as Results,
    archers: archers.result.data as unknown as ArcherResults,
  };
}

/**
 * Seed one event and open a results tab once it has loaded.
 *
 * @param doc - The event document.
 * @param tab - The tab's route name.
 */
async function openResults(doc: Record<string, unknown>, tab: string) {
  await page.goto("./");
  await seed(page, { events: [doc] });
  await page.goto(`./#/e/${doc.id as string}/results/${tab}`);
  await expect(page.getByRole("tab", { name: "Leaderboard" })).toBeVisible({ timeout: 240_000 });
}

/**
 * Every body row's cell texts.
 *
 * @param table - A table.
 * @returns One list of cell texts per row.
 */
const cells = (table: Locator) =>
  table
    .locator("tbody tr")
    .evaluateAll((rows) =>
      rows.map((row) => Array.from(row.querySelectorAll("td"), (td) => td.textContent ?? "")),
    );

const graphView = () => page.getByRole("switch", { name: "Graph view" });

for (const name of ["simple", "handicap_updating"]) {
  test(`${name}: every tab shows the bridge's values exactly`, async () => {
    const { doc, results, archers } = scenario(name, `ev-${name}`);
    const start = results.show_start_handicap;

    await openResults(doc, "leaderboard");
    await expect(page).toHaveTitle(/^Results: Leaderboard/);
    await expect
      .poll(() => cells(page.getByTestId("leaderboard-table")))
      .toEqual(
        results.leaderboard.map((r) => [
          r.rank,
          r.name,
          r.points,
          r.passes_decided,
          r.starting_handicap,
          r.to_date_handicap,
        ]),
      );
    await expect(page.getByTestId("leaderboard-caption")).toContainText(
      `${results.completed_passes} of ${results.n_passes} so far`,
    );

    await page.getByRole("tab", { name: "Pairwise" }).click();
    await expect(page).toHaveURL(/results\/pairwise$/);
    await expect
      .poll(() => cells(page.getByTestId("pairwise-table")))
      .toEqual(results.pairwise.map((r) => [r.name_a, r.name_b, r.wins_a, r.wins_b, r.result]));

    await page.getByRole("tab", { name: "Passes" }).click();
    await expect(page).toHaveURL(/results\/passes$/);
    const tables = page.getByTestId("passes").getByTestId("pass-table");
    await expect(tables).toHaveCount(results.passes.length);
    for (const [i, pass] of results.passes.entries()) {
      await expect
        .poll(() => cells(tables.nth(i)))
        .toEqual(
          pass.groups
            .flat()
            .map((r) => [
              r.archer,
              r.score,
              r.percentile,
              ...(start ? [r.start_handicap] : []),
              r.handicap,
              r.winner,
            ]),
        );
    }

    await page.getByRole("tab", { name: "Archers" }).click();
    await expect(page).toHaveURL(/results\/archers$/);
    const sections = page.getByTestId("archer-section");
    await expect(sections).toHaveCount(archers.sections.length);
    for (const [i, s] of archers.sections.entries()) {
      await expect(sections.nth(i).getByRole("heading")).toHaveText(s.name);
      await expect(sections.nth(i).getByTestId("archer-heading")).toHaveText(
        `Total score ${s.total_score} - starting handicap ${s.starting_handicap} - to-date handicap ${s.to_date_handicap}`,
      );
      const expected = s.rows.map((r) => [
        r.pass_number,
        r.opponent,
        r.score,
        r.percentile,
        ...(start ? [r.start_handicap] : []),
        r.handicap,
      ]);
      if (s.average) {
        const a = s.average;
        expected.push([
          "Average",
          a.score,
          a.percentile,
          ...(start ? [a.start_handicap] : []),
          a.handicap,
        ]);
      }
      await expect.poll(() => cells(sections.nth(i).locator("table"))).toEqual(expected);
    }
  });
}

test("each tab is reachable by its hash route", async () => {
  const { doc } = scenario("simple", "ev-r");
  for (const [tab, label] of [
    ["leaderboard", "Leaderboard"],
    ["pairwise", "Pairwise"],
    ["passes", "Passes"],
    ["archers", "Archers"],
  ]) {
    await openResults(doc, tab);
    await expect(page.getByRole("tab", { name: label })).toHaveAttribute("aria-selected", "true");
    await expect(page).toHaveTitle(new RegExp(`^Results: ${label}`));
  }
});

test("the Passes tab opens the latest scored pass by default", async () => {
  const { doc, results } = scenario("simple", "ev-p");
  await openResults(doc, "passes");
  const tables = page.getByTestId("passes").getByTestId("pass-table");
  const last = results.passes.length - 1;
  await expect(tables.nth(last)).toBeVisible();
  for (let i = 0; i < last; i++) await expect(tables.nth(i)).toBeHidden();
  await page.getByRole("button", { name: `Pass ${results.passes[0].pass_number}` }).click();
  await expect(tables.nth(0)).toBeVisible();
});

test("'View chart' opens the pair chart with Graph view on, and is absent with it off", async () => {
  const { doc, results } = scenario("simple", "ev-v");
  await openResults(doc, "pairwise");
  await expect(page.getByRole("button", { name: /^View chart/ })).toHaveCount(0);
  await graphView().check();
  await expect(page.getByRole("button", { name: /^View chart/ })).toHaveCount(
    results.pairwise.length,
  );
  const first = results.pairwise[0];
  await page
    .getByRole("button", { name: `View chart: ${first.name_a} and ${first.name_b}` })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByTestId("pair-chart")).toBeVisible();
  await expect(dialog.getByTestId("pair-chart")).toHaveAttribute(
    "aria-label",
    new RegExp(`${first.name_a}.*${first.name_b}`),
  );
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await graphView().uncheck();
  await expect(page.getByRole("button", { name: /^View chart/ })).toHaveCount(0);
});

test("before any pass is complete the Archers tab says so", async () => {
  const doc = fixtureDoc("start_event", { id: "ev-none" });
  await openResults(doc, "archers");
  await expect(page.getByTestId("no-completed-pass")).toHaveText(
    "No pass has been completed yet, so there are no results to show. They appear here once every match in a pass has been scored.",
  );
  await page.getByRole("tab", { name: "Passes" }).click();
  await expect(page.getByText("No pass has been scored yet.")).toBeVisible();
});
