import { expect, test } from "@playwright/test";


const EMAIL = process.env.E2E_EMAIL;
const PASSWORD = process.env.E2E_PASSWORD;

test.beforeAll(() => {
  if (!EMAIL || !PASSWORD) {
    throw new Error("E2E_EMAIL and E2E_PASSWORD are required for authentication tests");
  }
});

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Adresse email").fill(EMAIL!);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD!);
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/auth/login") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Se connecter" }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.status()).toBe(200);
  await expect(page).toHaveURL("/dashboard");
}

test("redirige un visiteur sans session vers la page de connexion", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL("/login");
});

test("supprime la session lors de la déconnexion", async ({ page }) => {
  await login(page);

  await expect(page.getByRole("heading", { name: "Dashboard exécutif" })).toBeVisible();
  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL("/login");

  await page.goto("/dashboard");
  await expect(page).toHaveURL("/login");
});
