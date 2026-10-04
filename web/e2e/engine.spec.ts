import { expect, test } from "@playwright/test";

/**
 * The Python engine in a real browser (UISpec.md 8, UI-7 and UI-9): the module worker loads
 * Pyodide from jsDelivr and the packages, and "New event" creates an event through the bridge,
 * stores it and opens Stage 1. Also prints the first-load transfer for the logbook, which must not
 * include the PDF library (fpdf2 is installed on the first PDF export, decision D16). Needs network.
 */
test("New event creates an event through the engine and opens Stage 1", async ({ page }) => {
  test.setTimeout(300_000);
  const transferred = new Map<string, number>();
  page.on("requestfinished", async (request) => {
    const sizes = await request.sizes();
    transferred.set(request.url(), sizes.responseBodySize + sizes.responseHeadersSize);
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("./");
  await page.getByRole("button", { name: "New event" }).first().click();
  await expect(page).toHaveURL(/#\/e\/[0-9a-f-]+\/setup\/1$/, { timeout: 240_000 });
  await expect(page.getByRole("heading", { name: "Stage 1" })).toBeVisible();
  await expect(page.getByTestId("header-event-name")).toContainText("New event");
  await expect(page.getByText("Getting the scoring engine ready")).toHaveCount(0);

  const total = [...transferred.values()].reduce((sum, size) => sum + size, 0);
  console.log(`First load: ${(total / 1e6).toFixed(1)} MB in ${transferred.size} requests.`);
  expect(errors).toEqual([]);
  expect(total).toBeGreaterThan(5e6);
  expect([...transferred.keys()].filter((url) => /fpdf2|pillow|fonttools/i.test(url))).toEqual([]);

  await page.goto("./");
  await expect(page.getByTestId("resume-card")).toContainText("New event");
});
