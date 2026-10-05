import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

/**
 * UI-10: the handicap calculator against the UI-5 calculator fixture, through the real engine.
 * One page is shared so the engine starts once (it downloads about 10 MB).
 */

interface Step {
  command: string;
  payload: { kind: "indoor" | "outdoor"; round_codename: string; compound: boolean; score: string };
  result:
    | { ok: true; data: { text: string } }
    | { ok: false; error: { message: string } }
    | {
        ok: true;
        data: { calculator: { rounds: Record<string, { value: string; label: string }[]> } };
      };
}

const FIXTURE = JSON.parse(
  readFileSync(
    path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      "../../tests/fixtures/bridge/calculator.json",
    ),
    "utf8",
  ),
) as { steps: Step[] };
const ROUNDS = (
  FIXTURE.steps[0].result as {
    data: { calculator: { rounds: Record<string, { value: string; label: string }[]> } };
  }
).data.calculator.rounds;
const CASES = FIXTURE.steps.filter((step) => step.command === "calculator");

test.describe.configure({ mode: "serial", timeout: 240_000 });
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await page.goto("./#/calculator");
  await expect(page.getByRole("button", { name: "Calculate" })).toBeVisible({ timeout: 240_000 });
});

test.afterAll(async () => {
  await page.close();
});

/**
 * Fill the form for one fixture case and calculate.
 *
 * @param step - A `calculator` step from the fixture.
 */
async function calculate(step: Step) {
  const { kind, round_codename, compound, score } = step.payload;
  await page.getByText(kind === "indoor" ? "Indoor" : "Outdoor", { exact: true }).click();
  const label = ROUNDS[kind].find((r) => r.value === round_codename)!.label;
  await page.getByRole("combobox", { name: "Round" }).click();
  await page.getByRole("option", { name: label, exact: true }).click();
  if (kind === "indoor") {
    const box = page.getByRole("checkbox", { name: "Shot with a compound bow" });
    if ((await box.isChecked()) !== compound) await box.click();
  }
  await page.getByLabel("Full round score").fill(score);
  await page.getByRole("button", { name: "Calculate" }).click();
}

for (const step of CASES.filter((s) => s.result.ok)) {
  const { kind, round_codename, compound, score } = step.payload;
  test(`${kind} ${round_codename}${compound ? " compound" : ""} ${score} shows the fixture handicap`, async () => {
    await calculate(step);
    const text = (step.result as { data: { text: string } }).data.text;
    await expect(page.getByTestId("calculator-result")).toHaveText(`Handicap: ${text}`);
  });
}

test("invalid input shows the bridge's validation message", async () => {
  const invalid = CASES.find((s) => !s.result.ok)!;
  const message = (invalid.result as { error: { message: string } }).error.message;
  // The number input refuses letters, so leave it empty: the bridge rejects that the same way.
  await calculate({ ...invalid, payload: { ...invalid.payload, score: "" } });
  await expect(page.getByTestId("calculator-error")).toHaveText(message);
  await expect(page.getByTestId("calculator-result")).toHaveCount(0);
});

test("the compound checkbox is shown for Indoor and hidden for Outdoor", async () => {
  const box = page.getByRole("checkbox", { name: "Shot with a compound bow" });
  await page.getByText("Indoor", { exact: true }).click();
  await expect(box).toBeVisible();
  await page.getByText("Outdoor", { exact: true }).click();
  await expect(box).toHaveCount(0);
});

test("the round list changes between Indoor and Outdoor", async () => {
  for (const kind of ["indoor", "outdoor"] as const) {
    await page.getByText(kind === "indoor" ? "Indoor" : "Outdoor", { exact: true }).click();
    await page.getByRole("combobox", { name: "Round" }).click();
    await expect(page.getByRole("option")).toHaveCount(ROUNDS[kind].length);
    await expect(page.getByRole("option").first()).toHaveText(ROUNDS[kind][0].label);
    await page.keyboard.press("Escape");
  }
});
