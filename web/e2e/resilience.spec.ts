import { readFileSync } from "node:fs";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { fixtureDoc, readStored, seed } from "./seed";

/**
 * UI-20: resilience (UISpec.md 6, its failure modes paragraph, and 7.6; deploymentConstrains 8,
 * item 3), through the real engine. Each test has its own browser context: on WebKit, many tabs
 * opened and closed in one context eventually left the engine unable to start.
 */

test.describe.configure({ mode: "serial", timeout: 240_000 });
const ENGINE_TIMEOUT = 240_000;
let context: BrowserContext;
let page: Page;

test.beforeEach(async ({ browser }) => {
  context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
  await page.goto("./");
});

test.afterEach(async () => {
  await context.close();
});

type Doc = Record<string, unknown> & {
  id: string;
  archers: { name: string }[];
  assignment: number[];
  scores: Record<string, Record<string, { scores: Record<string, number> }>>;
};

/**
 * Seed one event and open a route of it.
 *
 * @param doc - The event document.
 * @param hash - The route, e.g. "#/e/ev/setup/2".
 */
async function open(doc: Doc, hash: string) {
  await page.goto("./");
  await seed(page, { events: [doc] });
  await page.goto(`./${hash}`);
}

/**
 * Close the tab and open the app's bare URL in a new one, as a user returning later would, then
 * press Resume on the Home card.
 */
async function closeAndResume() {
  await page.close();
  page = await context.newPage();
  await page.goto("./");
  await expect(page.getByTestId("resume-card")).toBeVisible();
  await page.getByRole("button", { name: "Resume" }).click();
}

/**
 * The stored event.
 *
 * @param id - The event id.
 * @returns The stored document.
 */
const stored = async (id: string) => (await readStored(page, `event:${id}`)) as Doc;

/**
 * Wait until the draft store holds a value for a form, so closing the tab does not race the
 * debounced draft save.
 *
 * @param id - The event id.
 * @param form - The draft's form key, e.g. "stage1".
 */
async function draftSaved(id: string, form: string) {
  await expect
    .poll(async () => Object.keys(((await readStored(page, `draft:${id}`)) as object) ?? {}), {
      timeout: 5000,
    })
    .toContain(form);
}

// First in the file: on WebKit, after the other tests have started the engine several times in
// the same browser, a restart after this test's aborted downloads sometimes never finished.
test("an engine that cannot start shows the message with Retry and Reload, and stored data is unchanged", async () => {
  const offline = await context.browser()!.newContext({ viewport: { width: 1440, height: 900 } });
  const tab = await offline.newPage();
  const doc = fixtureDoc("record_match@0", { id: "ev-e" }) as Doc;
  await tab.goto("./");
  await seed(tab, { events: [doc] });
  // Offline on a first visit: Pyodide's CDN cannot be reached.
  await offline.route("https://cdn.jsdelivr.net/**", (route) => route.abort());
  await tab.goto("./#/e/ev-e/pass");
  await tab.reload();
  const alert = tab.getByRole("alert").filter({ hasText: "The scoring engine could not start" });
  await expect(alert).toBeVisible({ timeout: ENGINE_TIMEOUT });
  await expect(alert.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(alert.getByRole("button", { name: "Reload the page" })).toBeVisible();
  expect(await readStored(tab, "event:ev-e")).toEqual(doc);
  // Back online, Retry starts the engine and the pass loads from the untouched event.
  await offline.unroute("https://cdn.jsdelivr.net/**");
  await alert.getByRole("button", { name: "Retry" }).click();
  await expect(tab.getByTestId("overview-table")).toBeVisible({ timeout: ENGINE_TIMEOUT });
  await offline.close();
});

test.describe("close and reopen the tab", () => {
  test("at Stage 1: resumes at Stage 1 with the typed value", async () => {
    const doc = fixtureDoc("new_document", { id: "ev-r1", name: "Resume one" }) as Doc;
    await open(doc, "#/e/ev-r1/setup/1");
    const archers = page.getByLabel("Number of archers");
    await expect(archers).toBeEditable({ timeout: ENGINE_TIMEOUT });
    await archers.fill("6");
    await draftSaved("ev-r1", "stage1");
    await closeAndResume();
    await expect(page).toHaveURL(/#\/e\/ev-r1\/setup\/1$/);
    await expect(page.getByLabel("Number of archers")).toHaveValue("6", {
      timeout: ENGINE_TIMEOUT,
    });
  });

  test("at Stage 2: resumes at Stage 2 with the typed name", async () => {
    const doc = fixtureDoc("apply_stage1", { id: "ev-r2", name: "Resume two" }) as Doc;
    await open(doc, "#/e/ev-r2/setup/2");
    const name = page.getByLabel("Name, archer 1");
    await expect(name).toBeEditable({ timeout: ENGINE_TIMEOUT });
    await name.fill("Zed");
    await draftSaved("ev-r2", "stage2");
    await closeAndResume();
    await expect(page).toHaveURL(/#\/e\/ev-r2\/setup\/2$/);
    await expect(page.getByLabel("Name, archer 1")).toHaveValue("Zed", {
      timeout: ENGINE_TIMEOUT,
    });
  });

  test("at Stage 3: resumes at Stage 3 with the same pairings", async () => {
    const doc = fixtureDoc("apply_stage2", { id: "ev-r3", name: "Resume three" }) as Doc;
    await open(doc, "#/e/ev-r3/setup/3");
    const table = page.getByRole("table");
    await expect(table).toBeVisible({ timeout: ENGINE_TIMEOUT });
    const before = await table.textContent();
    await closeAndResume();
    await expect(page).toHaveURL(/#\/e\/ev-r3\/setup\/3$/);
    await expect(page.getByRole("table")).toHaveText(before ?? "", { timeout: ENGINE_TIMEOUT });
    expect((await stored("ev-r3")).assignment).toEqual(doc.assignment);
  });

  test("mid-score: resumes at the match with the typed score, and no saved score is lost", async () => {
    const doc = fixtureDoc("record_match@0", { id: "ev-r4", name: "Resume four" }) as Doc;
    await open(doc, "#/e/ev-r4/pass/match/1");
    const first = page.getByLabel(/score \(0-\d+\)$/).first();
    await expect(first).toBeEditable({ timeout: ENGINE_TIMEOUT });
    await first.fill("77");
    await draftSaved("ev-r4", "match:0:1");
    await closeAndResume();
    await expect(page).toHaveURL(/#\/e\/ev-r4\/pass\/match\/1$/);
    await expect(page.getByLabel(/score \(0-\d+\)$/).first()).toHaveValue("77", {
      timeout: ENGINE_TIMEOUT,
    });
    expect((await stored("ev-r4")).scores).toEqual(doc.scores);
  });
});

test("a forced reload during a save loses no saved score and leaves a valid stored event", async () => {
  const doc = fixtureDoc("record_match@0", { id: "ev-f" }) as Doc;
  await open(doc, "#/e/ev-f/pass/match/1");
  const inputs = page.getByLabel(/score \(0-\d+\)$/);
  await expect(inputs.first()).toBeEditable({ timeout: ENGINE_TIMEOUT });
  await inputs.nth(0).fill("101");
  await inputs.nth(1).fill("99");
  await page.getByRole("button", { name: "Save scores" }).click();
  await page.reload();
  const after = await stored("ev-f");
  // Either the save finished before the reload or it never reached storage; never a half-write.
  expect(after.scores["0"]["0"]).toEqual(doc.scores["0"]["0"]);
  if (after.scores["0"]["1"] !== undefined) {
    expect(Object.values(after.scores["0"]["1"].scores).sort()).toEqual([101, 99].sort());
  }
  // The stored event still opens: the overview loads through the engine from it.
  await page.goto("./#/e/ev-f/pass");
  await expect(page.getByTestId("overview-table")).toBeVisible({ timeout: ENGINE_TIMEOUT });
  await expect(page.getByTestId("overview-table").locator("tbody tr").first()).toContainText(
    "Scored",
  );
});

test.describe("two tabs on the same event", () => {
  /**
   * Save scores for match 0 in a tab.
   *
   * @param tab - The tab.
   * @param a - The first archer's score.
   * @param b - The second archer's score.
   */
  async function saveIn(tab: Page, a: number, b: number) {
    const inputs = tab.getByLabel(/score \(0-\d+\)$/);
    await inputs.nth(0).fill(String(a));
    await inputs.nth(1).fill(String(b));
    await tab.getByRole("button", { name: /^Save/ }).click();
  }

  for (const choice of ["Load latest", "Overwrite with this tab"] as const) {
    test(`a stale tab's save shows the conflict modal; "${choice}" works`, async () => {
      const doc = fixtureDoc("start_event", { id: "ev-t" }) as Doc;
      await open(doc, "#/e/ev-t/pass/match/0");
      const other = await context.newPage();
      await other.goto("./#/e/ev-t/pass/match/0");
      for (const tab of [page, other]) {
        await expect(tab.getByLabel(/score \(0-\d+\)$/).first()).toBeEditable({
          timeout: ENGINE_TIMEOUT,
        });
      }
      await saveIn(other, 100, 90);
      await expect(other.getByTestId("match-saved")).toBeVisible();
      await saveIn(page, 80, 110);
      const modal = page.getByRole("dialog", { name: "This event changed in another tab" });
      await expect(modal).toBeVisible();
      await expect(modal.getByRole("button", { name: "Load latest" })).toBeVisible();
      await expect(modal.getByRole("button", { name: "Overwrite with this tab" })).toBeVisible();
      await modal.getByRole("button", { name: choice }).click();
      await expect(modal).toHaveCount(0);
      const kept = choice === "Load latest" ? [100, 90] : [80, 110];
      await expect
        .poll(async () => Object.values((await stored("ev-t")).scores["0"]?.["0"]?.scores ?? {}))
        .toEqual(kept);
      await other.close();
    });
  }
});

test("with storage unavailable the persistent NOT-saved alert offers Download backup", async () => {
  const blocked = await context.browser()!.newContext({ viewport: { width: 1440, height: 900 } });
  const tab = await blocked.newPage();
  // A private window or a blocked site: opening the database fails.
  await tab.addInitScript(() => {
    const failing = Object.create(IDBFactory.prototype) as IDBFactory;
    Object.defineProperty(failing, "open", {
      value: () => {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    });
    Object.defineProperty(window, "indexedDB", { value: failing, configurable: true });
  });
  await tab.goto("./");
  await tab.getByRole("button", { name: "New event" }).click();
  const alert = tab.getByRole("alert").filter({ hasText: "This event is NOT being saved" });
  await expect(alert).toBeVisible({ timeout: ENGINE_TIMEOUT });
  // The alert shows from the start (Home could not read the saved events); its backup button
  // appears once the new event, built by the engine, has failed to save.
  await expect(alert.getByRole("button", { name: "Download backup" })).toBeVisible({
    timeout: ENGINE_TIMEOUT,
  });
  const [download] = await Promise.all([
    tab.waitForEvent("download"),
    alert.getByRole("button", { name: "Download backup" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.json$/);
  // The backup holds the new event that could not be stored.
  const backup = JSON.parse(readFileSync(await download.path(), "utf-8")) as {
    events: { schema_version: number; status: string }[];
  };
  expect(backup.events).toHaveLength(1);
  expect(backup.events[0].status).toBe("setup");
  await blocked.close();
});
