import { expect, type Page } from "@playwright/test";
import { fixtureDoc, seed } from "./seed";

/**
 * Every view the app has, with the seeded events that reach them, for the review screenshots and
 * the accessibility and layout checks (UI-19). A `graph` route turns Graph view on and shows every
 * pass's markers (`openChart` first opens the first pairwise chart).
 */
export interface ReviewRoute {
  name: string;
  hash: string;
  /** The page title expected for this route. */
  title: string;
  graph?: boolean;
  openChart?: boolean;
}

export const ROUTES: ReviewRoute[] = [
  { name: "home", hash: "", title: "Handicapped H2Hs" },
  { name: "stage1", hash: "#/e/ev-setup/setup/1", title: "Stage 1" },
  { name: "stage1-locked", hash: "#/e/ev-run/setup/1", title: "Stage 1" },
  { name: "stage2", hash: "#/e/ev-setup/setup/2", title: "Stage 2" },
  { name: "stage2-advanced", hash: "#/e/ev-adv/setup/2", title: "Stage 2" },
  { name: "stage2-locked", hash: "#/e/ev-run/setup/2", title: "Stage 2" },
  { name: "stage3", hash: "#/e/ev-odd/setup/3", title: "Stage 3" },
  { name: "stage3-locked", hash: "#/e/ev-run/setup/3", title: "Stage 3" },
  { name: "pass", hash: "#/e/ev-run/pass", title: "Pass 1" },
  { name: "pass-complete", hash: "#/e/ev-done/pass", title: "Pass 3" },
  { name: "match-new", hash: "#/e/ev-run/pass/match/0", title: "Match 1" },
  { name: "match-saved", hash: "#/e/ev-done/pass/match/1", title: "Match 2" },
  { name: "match-chart", hash: "#/e/ev-chart/pass/match/1", title: "Match 2", graph: true },
  {
    name: "results-leaderboard",
    hash: "#/e/ev-done/results/leaderboard",
    title: "Results: Leaderboard",
  },
  { name: "results-pairwise", hash: "#/e/ev-done/results/pairwise", title: "Results: Pairwise" },
  {
    name: "results-pairwise-chart",
    hash: "#/e/ev-done/results/pairwise",
    title: "Results: Pairwise",
    graph: true,
    openChart: true,
  },
  { name: "results-passes", hash: "#/e/ev-done/results/passes", title: "Results: Passes" },
  { name: "results-archers", hash: "#/e/ev-done/results/archers", title: "Results: Archers" },
  { name: "results-archers-none", hash: "#/e/ev-run/results/archers", title: "Results: Archers" },
  { name: "calculator", hash: "#/calculator", title: "Handicap calculator" },
  { name: "about", hash: "#/about", title: "About" },
  { name: "not-found", hash: "#/e/missing/pass", title: "Event not found" },
];

/**
 * Seed the review events, open a route and wait until it has settled (engine ready, nothing
 * loading, the chart drawn for a `graph` route).
 *
 * @param page - A page on the app.
 * @param route - The route.
 */
export async function openRoute(page: Page, route: ReviewRoute): Promise<void> {
  await page.goto("./");
  await seed(page, {
    events: [
      fixtureDoc("apply_stage1", { id: "ev-setup", name: "Club night 3 Oct" }),
      fixtureDoc("start_event", { id: "ev-run", name: "League round 2" }),
      fixtureDoc("apply_stage1", { id: "ev-adv", name: "Mixed targets" }, "advanced"),
      fixtureDoc("redraw", { id: "ev-odd", name: "Five archers" }, "byes_sat_out"),
      fixtureDoc("record_match@-1", { id: "ev-done", name: "Finished night" }),
      fixtureDoc("record_match@4", { id: "ev-chart", name: "Chart night" }),
    ],
  });
  await page.goto(`./${route.hash}`);
  // The shell (with the engine banner, while it shows) renders after settings are read.
  await page.getByRole("button", { name: "Colour scheme" }).waitFor();
  await page
    .getByText("Getting the scoring engine ready")
    .waitFor({ state: "detached", timeout: 200_000 });
  await expect(page.locator('[aria-label^="Loading"]:visible')).toHaveCount(0, { timeout: 60_000 });
  if (route.graph) {
    await page.getByRole("switch", { name: "Graph view" }).check();
    if (route.openChart)
      await page
        .getByRole("button", { name: /^View chart/ })
        .first()
        .click();
    await page.getByRole("checkbox", { name: "Show previous passes' scores too" }).check();
    await page.getByTestId("pair-chart").waitFor();
    await page.waitForTimeout(500); // let a modal finish fading in
  }
}
