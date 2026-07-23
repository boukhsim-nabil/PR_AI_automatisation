import { expect, test } from "@playwright/test";


const EMAIL = process.env.E2E_EMAIL;
const VALID_PASSWORD = process.env.E2E_PASSWORD;

test.beforeAll(() => {
  if (!EMAIL || !VALID_PASSWORD) {
    throw new Error("E2E_EMAIL and E2E_PASSWORD are required for authentication tests");
  }
});


test("affiche une erreur explicite sans recharger la page si le mot de passe est invalide", async ({
  page,
}) => {
  await page.goto("/login");
  const documentMarker = await page.evaluate(() => {
    const marker = crypto.randomUUID();
    Reflect.set(window, "__e2eDocumentMarker", marker);
    return marker;
  });

  await page.getByLabel("Adresse email").fill(EMAIL!);
  await page.getByLabel("Mot de passe", { exact: true }).fill("FauxMotDePasse!123");
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(page.locator("#login-error")).toContainText(
    "Connexion impossible. Vérifiez vos informations ou contactez votre administrateur.",
  );
  await expect(page).toHaveURL("/login");
  await expect
    .poll(() => page.evaluate(() => Reflect.get(window, "__e2eDocumentMarker")))
    .toBe(documentMarker);
});


test("redirige vers le dashboard avec des identifiants valides", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Adresse email").fill(EMAIL!);
  await page.getByLabel("Mot de passe", { exact: true }).fill(VALID_PASSWORD!);
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/auth/login") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Se connecter" }).click();
  const loginResponse = await loginResponsePromise;

  expect(loginResponse.status()).toBe(200);
  await expect(page).toHaveURL("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Dashboard exécutif" }),
  ).toBeVisible();
});
