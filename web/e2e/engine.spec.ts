import { expect, test } from "@playwright/test";

/**
 * The Python engine in a real browser (UISpec.md 8, task UI-7): the module worker loads Pyodide
 * from jsDelivr, installs the packages, unpacks the hashed bundle and answers a bridge call. Also
 * measures the first-load transfer (a fresh browser context has an empty cache) and the start
 * time, printing them for the logbook. Needs network access.
 */
test("the engine starts in a module worker and answers a bridge call", async ({ page }) => {
  test.setTimeout(300_000);
  const transferred = new Map<string, number>();
  page.on("requestfinished", async (request) => {
    const sizes = await request.sizes();
    transferred.set(request.url(), sizes.responseBodySize + sizes.responseHeadersSize);
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  const started = Date.now();
  await page.goto("./");
  const status = page.getByTestId("engine-status");
  await expect(status).toHaveAttribute("data-state", "ready", { timeout: 240_000 });
  const wallSeconds = (Date.now() - started) / 1000;
  await expect(page.getByTestId("engine-check")).toHaveText(
    "Bowstyles: Recurve, Compound, Barebow, Longbow.",
  );

  const timings = JSON.parse((await status.getAttribute("data-timings")) ?? "{}");
  const total = [...transferred.values()].reduce((sum, size) => sum + size, 0);
  const largest = [...transferred.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([url, size]) => `${(size / 1e6).toFixed(2)} MB ${url.split("/").slice(-1)[0]}`);
  console.log(
    `First load: ${(total / 1e6).toFixed(1)} MB in ${transferred.size} requests; page to ready ${wallSeconds.toFixed(1)} s.`,
  );
  console.log(`Engine timings (ms): ${JSON.stringify(timings)}`);
  console.log(`Largest downloads:\n  ${largest.join("\n  ")}`);
  expect(errors).toEqual([]);
  expect(total).toBeGreaterThan(5e6); // the worker's downloads were counted
});
