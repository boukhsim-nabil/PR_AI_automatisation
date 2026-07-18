import { expect, test } from "@playwright/test";

test("la page d'accueil est accessible", async ({ page }) => {
  const response = await page.goto("/");

  expect(response?.ok()).toBeTruthy();
});
