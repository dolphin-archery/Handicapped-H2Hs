import { expect, test, type Page } from "@playwright/test";
import { fixtureDoc, seed } from "./seed";

/**
 * UI-16: the pair chart in the match view, through the real engine (shared page, serial). The
 * document is the simple fixture after the first pass-2 match was saved (index 1 = pass 2), so its
 * archers have markers from pass 1 too.
 */

const PASS2 = fixtureDoc("record_match@3", { id: "ev-c" });

test.describe.configure({ mode: "serial", timeout: 240_000 });
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("./");
});

test.afterAll(async () => {
  await page.close();
});

/** Open the scored match 0 of pass 2 once it has loaded. */
async function openMatch() {
  await page.goto("./");
  await seed(page, { events: [PASS2] });
  await page.goto("./#/e/ev-c/pass/match/0");
  await expect(page.getByRole("button", { name: "Save changed scores" })).toBeVisible({
    timeout: 240_000,
  });
}

const graphView = () => page.getByRole("switch", { name: "Graph view" });
const labels = async () =>
  JSON.parse((await page.getByTestId("pair-chart").getAttribute("data-marker-labels")) ?? "[]") as {
    text: string;
  }[];

test("with Graph view on the match view shows the chart; off, the muted hint", async () => {
  await openMatch();
  await expect(page.getByTestId("graph-view-off")).toBeVisible();
  await expect(page.getByTestId("pair-chart")).toHaveCount(0);
  await graphView().check();
  await expect(page.getByTestId("pair-chart")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Score distributions" })).toBeVisible();
  await expect(page.getByTestId("graph-view-off")).toHaveCount(0);
  await graphView().uncheck();
  await expect(page.getByTestId("pair-chart")).toHaveCount(0);
  await expect(page.getByTestId("graph-view-off")).toBeVisible();
});

test("the previous-passes checkbox adds earlier passes' markers", async () => {
  await openMatch();
  await graphView().check();
  await expect.poll(async () => (await labels()).map((l) => l.text)).toEqual(["P2", "P2"]);
  await page.getByRole("checkbox", { name: "Show previous passes' scores too" }).check();
  await expect
    .poll(async () => (await labels()).map((l) => l.text).sort())
    .toEqual(["P1", "P1", "P2", "P2"]);
  await page.getByRole("checkbox", { name: "Show previous passes' scores too" }).uncheck();
  await expect.poll(async () => (await labels()).length).toBe(2);
  await graphView().uncheck();
});

test("the explanation opens from 'How the winner is decided'", async () => {
  await openMatch();
  await graphView().check();
  await page.getByRole("button", { name: "How the winner is decided" }).click();
  await expect(page.getByText(/Whoever has the higher percentile/)).toBeVisible();
  await graphView().uncheck();
});
