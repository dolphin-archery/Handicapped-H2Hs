import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

/**
 * UI-21: a whole event through the production build, as a user runs it (UISpec.md 8, UI-21): New
 * event, Stage 1 to 3, every match of every pass scored, a reload part-way, Advance, the
 * completion alert's three downloads, and the event still complete after a reload.
 */

test("a full event runs from New event to the exports, surviving a reload", async ({ page }) => {
  test.setTimeout(600_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("./");
  await page.getByRole("button", { name: "New event" }).first().click();
  await expect(page).toHaveURL(/#\/e\/[0-9a-f-]+\/setup\/1$/, { timeout: 240_000 });

  // Stage 1: 4 archers, 36 arrows in 12-arrow passes (3 passes), simple setup.
  await page.getByLabel("Number of archers").fill("4");
  await page.getByLabel("Total arrows").fill("36");
  await page.getByRole("slider").focus();
  await page.keyboard.press("Home");
  for (let i = 0; i < 6; i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("n-pass-value")).toHaveText("12");
  await page.getByRole("button", { name: "Continue" }).click();

  // Stage 2: the archers.
  await expect(page).toHaveURL(/setup\/2$/);
  const archers = [
    ["Ann", "35"],
    ["Ben", "20"],
    ["Cat", "50"],
    ["Dan", "42"],
  ];
  await expect(page.getByLabel("Name, archer 1")).toBeEditable({ timeout: 240_000 });
  for (const [i, [name, handicap]] of archers.entries()) {
    await page.getByLabel(`Name, archer ${i + 1}`).fill(name);
    await page.getByRole("combobox", { name: `Bowstyle, archer ${i + 1}` }).click();
    await page.getByRole("option", { name: "Recurve", exact: true }).click();
    await page.getByLabel(`Handicap, archer ${i + 1}`).fill(handicap);
  }
  await page.getByRole("button", { name: "Continue" }).click();

  // Stage 3: confirm the draw.
  await expect(page).toHaveURL(/setup\/3$/);
  await page.getByRole("button", { name: "Confirm pairings and start event" }).click();
  await expect(page).toHaveURL(/\/pass$/);

  for (let pass = 1; pass <= 3; pass++) {
    await expect(page.getByRole("heading", { name: `Pass ${pass} of 3` })).toBeVisible();
    for (let match = 0; match < 2; match++) {
      await page.getByRole("link", { name: "Enter scores" }).first().click();
      const inputs = page.getByLabel(/score \(0-\d+\)$/);
      await expect(inputs.first()).toBeEditable();
      await inputs.nth(0).fill(String(100 + pass + match));
      await inputs.nth(1).fill(String(90 - pass));
      await page.getByRole("button", { name: "Save scores" }).click();
      await expect(page.getByTestId("match-saved")).toBeVisible();
      await page.getByRole("link", { name: "Back to overview" }).first().click();
      if (pass === 2 && match === 0) {
        // A reload mid-event: the saved match is still scored once the engine is back.
        await page.reload();
        await expect(page.getByTestId("scored-count")).toHaveText("1 of 2 matches scored", {
          timeout: 240_000,
        });
      }
    }
    await expect(page.getByTestId("scored-count")).toHaveText("2 of 2 matches scored");
    if (pass < 3) {
      await page.getByRole("button", { name: "Advance to next pass" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Advance" }).click();
    }
  }

  // The completion alert and its downloads.
  const alert = page.getByTestId("completion");
  await expect(alert).toBeVisible();
  for (const [label, pattern] of [
    ["Leaderboard (CSV)", /^leaderboard_\d{8}-\d{6}\.csv$/],
    ["Archer results (CSV)", /^archer-results_\d{8}-\d{6}\.csv$/],
    ["Full report (PDF)", /^results_\d{8}-\d{6}\.pdf$/],
  ] as const) {
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 240_000 }),
      alert.getByRole("button", { name: label }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(pattern);
    const bytes = readFileSync(await download.path());
    if (label.endsWith("(PDF)")) expect(bytes.subarray(0, 5).toString("latin1")).toBe("%PDF-");
    else for (const [name] of archers) expect(bytes.toString("utf-8")).toContain(name);
  }

  // The finished event survives a reload.
  await page.reload();
  await expect(page.getByTestId("completion")).toBeVisible({ timeout: 240_000 });
  await page.goto("./");
  await expect(page.getByTestId("event-card")).toContainText("Complete");
});
