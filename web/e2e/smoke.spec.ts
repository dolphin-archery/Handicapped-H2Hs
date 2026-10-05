import { expect, test } from "@playwright/test";

test("the built app loads with its title and the Home heading", async ({ page }) => {
  await page.goto("./");
  await expect(page).toHaveTitle("Handicapped H2Hs");
  await expect(page.getByRole("heading", { level: 1, name: "Events" })).toBeVisible();
});
