import { expect, test } from "@playwright/test";
import { fixtureDoc, seed } from "./seed";

/** UI-9: the app shell, Home, guards, Resume, rename, delete and corrupt-value recovery. */

const STAGE1 = fixtureDoc("apply_stage1", {
  id: "ev-setup",
  name: "Club night",
  updated_at: "2026-10-04T10:00:00.000Z",
});
const RUNNING = fixtureDoc("start_event", {
  id: "ev-run",
  name: "League round",
  updated_at: "2026-10-04T12:00:00.000Z",
});

test.beforeEach(async ({ page }) => {
  await page.goto("./");
});

test("a guarded route redirects to the earlier stage with a notification", async ({ page }) => {
  await seed(page, { events: [STAGE1] });
  await page.goto("./#/e/ev-setup/setup/3");
  await expect(page).toHaveURL(/#\/e\/ev-setup\/setup\/2$/);
  await expect(page.getByText("Complete Stage 2 first.")).toBeVisible();
  await page.goto("./#/e/ev-setup/pass");
  await expect(page).toHaveURL(/#\/e\/ev-setup\/setup\/2$/);
  await expect(page.getByText(/The event has not started yet/)).toBeVisible();
});

test("an unknown event id shows Event not found with a link Home", async ({ page }) => {
  await page.goto("./#/e/no-such-event/setup/1");
  await expect(page.getByRole("heading", { name: "Event not found" })).toBeVisible();
  await page.getByRole("link", { name: "Go to Home" }).click();
  await expect(page).toHaveURL(/#\/$/);
});

test("an unknown hash goes Home", async ({ page }) => {
  await page.goto("./#/nowhere/at/all");
  await expect(page).toHaveURL(/#\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Events" })).toBeVisible();
});

test("Home shows the empty state with no saved events", async ({ page }) => {
  await expect(page.getByText(/Start a new event to set up the archers/)).toBeVisible();
  await expect(page.getByTestId("resume-card")).toHaveCount(0);
});

test("with two in-progress events the Resume card shows the most recently updated, and both are listed", async ({
  page,
}) => {
  await seed(page, {
    events: [STAGE1, RUNNING],
    sessions: { "ev-run": "/e/ev-run/results/pairwise" },
  });
  const resume = page.getByTestId("resume-card");
  await expect(resume).toContainText("League round");
  await expect(page.getByTestId("event-card")).toHaveCount(2);
  await resume.getByRole("button", { name: "Resume" }).click();
  await expect(page).toHaveURL(/#\/e\/ev-run\/results\/pairwise$/);
});

test("Resume after reopening the tab restores the last route", async ({ page, context }) => {
  await seed(page, { events: [STAGE1] });
  await page.goto("./#/e/ev-setup/setup/2");
  await expect(page.getByRole("heading", { name: "Stage 2" })).toBeVisible();
  await page.close();
  const reopened = await context.newPage();
  await reopened.goto("./");
  await reopened.getByTestId("resume-card").getByRole("button", { name: "Resume" }).click();
  await expect(reopened).toHaveURL(/#\/e\/ev-setup\/setup\/2$/);
});

test("renaming from Home and from the header shows in both places after a reload, with Saved HH:MM", async ({
  page,
}) => {
  await seed(page, { events: [STAGE1] });
  const card = page.getByTestId("event-card");
  await card.getByRole("button", { name: "Rename" }).click();
  await page.getByLabel("Event name").fill("Renamed on Home");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(card).toContainText("Renamed on Home");

  await card.getByRole("button", { name: "Open" }).click();
  await page.getByTestId("header-event-name").click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.getByLabel("Event name").fill("Renamed in header");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByTestId("save-indicator")).toHaveText(/^Saved \d\d:\d\d$/);
  await page.reload();
  await expect(page.getByTestId("header-event-name")).toContainText("Renamed in header");
  await page.goto("./#/");
  await expect(page.getByTestId("event-card")).toContainText("Renamed in header");
});

test("a corrupt stored event is shown with export and delete, and the rest of Home works", async ({
  page,
}) => {
  const index = [
    {
      id: "ev-run",
      name: "League round",
      status: "running",
      updated_at: "2026-10-04T12:00:00.000Z",
      n_archers: 4,
    },
    {
      id: "ev-bad",
      name: "Broken event",
      status: "setup",
      updated_at: "2026-10-04T09:00:00.000Z",
      n_archers: 4,
    },
  ];
  await seed(page, { events: [RUNNING], index }, { "ev-bad": "not an event" });
  const corrupt = page.getByTestId("corrupt-card");
  await expect(corrupt).toContainText("This saved event cannot be read");
  await expect(page.getByTestId("event-card")).toContainText("League round");
  const download = page.waitForEvent("download");
  await corrupt.getByRole("button", { name: "Download what can be read" }).click();
  expect((await download).suggestedFilename()).toMatch(/^backup_\d{8}-\d{6}\.json$/);
  await corrupt.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete event" }).click();
  await expect(page.getByTestId("corrupt-card")).toHaveCount(0);
  await expect(page.getByTestId("event-card")).toHaveCount(1);
});

test("deleting an event asks for confirmation naming it, then removes it from Home", async ({
  page,
}) => {
  await seed(page, { events: [STAGE1] });
  await page.getByTestId("event-card").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("dialog")).toContainText('Delete "Club night"?');
  await page.getByRole("button", { name: "Keep it" }).click();
  await expect(page.getByTestId("event-card")).toHaveCount(1);
  await page.getByTestId("event-card").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete event" }).click();
  await expect(page.getByTestId("event-card")).toHaveCount(0);
  await expect(page.getByText(/Start a new event to set up the archers/)).toBeVisible();
});

test("navbar items not yet reachable are disabled", async ({ page }) => {
  await seed(page, { events: [STAGE1] });
  await page.goto("./#/e/ev-setup/setup/2");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByText("Current pass")).toBeVisible();
  await expect(nav.locator("[data-disabled]", { hasText: "Current pass" })).toHaveCount(1);
});

test("the root 404.html is published with a link to the app", async ({ request }) => {
  const response = await request.get("./404.html");
  expect(response.ok()).toBe(true);
  expect(await response.text()).toContain('href="/Handicapped-H2Hs/"');
});
