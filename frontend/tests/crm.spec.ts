import { expect, test, type Page } from "@playwright/test";

const OWNER_EMAIL = process.env.E2E_EMAIL;
const OWNER_PASSWORD = process.env.E2E_PASSWORD;
const VIEWER_EMAIL = process.env.E2E_VIEWER_EMAIL;
const VIEWER_PASSWORD = process.env.E2E_VIEWER_PASSWORD;
const SEEDED_LEAD_ID = "88888888-8888-4888-8888-888888888888";
const FOREIGN_LEAD_ID = "66666666-6666-4666-8666-666666666666";

let createdLeadId = "";
let createdProspectName = "";

test.beforeAll(() => {
  if (!OWNER_EMAIL || !OWNER_PASSWORD || !VIEWER_EMAIL || !VIEWER_PASSWORD) {
    throw new Error("CRM E2E identities are not configured");
  }
});

async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(password);
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/auth/login") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Se connecter" }).click();
  expect((await loginResponsePromise).status()).toBe(200);
  await expect(page).toHaveURL("/dashboard", { timeout: 15_000 });
}

test.describe.serial("CRM opérationnel", () => {
  test("1. donne accès à la page CRM", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.getByRole("link", { name: "CRM", exact: true }).first().click();
    await expect(page).toHaveURL("/dashboard/crm");
    await expect(page.getByRole("heading", { name: "Prospects", exact: true })).toBeVisible();
    await expect(page.getByText("Total prospects")).toBeVisible();
  });

  test("2. crée un contact et son premier prospect", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto("/dashboard/crm/leads/new");
    createdProspectName = `Prospect Playwright ${Date.now()}`;
    await page.getByLabel(/Nom.*obligatoire/).fill(createdProspectName);
    await page.getByRole("textbox", { name: "Email", exact: true })
      .fill(`crm-${Date.now()}@example.com`);
    await page.getByLabel("Organisation").fill("Playwright Industries");
    await page.getByLabel(/Intitulé.*obligatoire/).fill("Projet CRM automatisé");
    await page.getByLabel("Priorité").selectOption("high");
    const leadResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/crm/leads") && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Créer le contact et le prospect" }).click();
    const leadResponse = await leadResponsePromise;
    expect(leadResponse.status()).toBe(201);
    const created = (await leadResponse.json()) as { id: string };
    expect(created.id).toMatch(/^[0-9a-f-]{36}$/i);
    await expect(page).toHaveURL(/\/dashboard\/crm\/leads\/[0-9a-f-]{36}$/i, {
      timeout: 15_000,
    });
    createdLeadId = created.id;
    expect(createdLeadId).not.toBe("");
    await expect(page.getByRole("heading", { name: createdProspectName })).toBeVisible();
  });

  test("3. affiche le nouveau prospect dans la liste", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto(`/dashboard/crm?search=${encodeURIComponent(createdProspectName)}`);
    await expect(page.getByRole("row").filter({ hasText: createdProspectName })).toBeVisible();
  });

  test("4. ouvre la fiche détaillée d’un prospect", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto(`/dashboard/crm/leads/${createdLeadId}`);
    await expect(page.getByRole("heading", { name: createdProspectName })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Chronologie" })).toBeVisible();
  });

  test("5. change le statut d’un prospect", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto(`/dashboard/crm/leads/${SEEDED_LEAD_ID}`);
    await page.getByLabel("Statut").selectOption("qualified");
    await page.getByRole("button", { name: "Mettre à jour" }).click();
    await expect(page.getByText("Statut mis à jour.")).toBeVisible();
    await expect(page.getByText("Statut modifié", { exact: true }).first()).toBeVisible();
  });

  test("6. ajoute une note à la chronologie", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto(`/dashboard/crm/leads/${SEEDED_LEAD_ID}`);
    const subject = `Note Playwright ${Date.now()}`;
    await page.getByLabel("Sujet").fill(subject);
    await page.getByLabel("Note").fill("Compte rendu synthétique du test E2E.");
    await page.getByRole("button", { name: "Ajouter la note" }).click();
    await expect(page.getByText("Note ajoutée.")).toBeVisible();
    await expect(page.getByText(subject)).toBeVisible();
  });

  test("7. crée puis clôture une tâche", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto(`/dashboard/crm/leads/${SEEDED_LEAD_ID}`);
    const title = `Tâche Playwright ${Date.now()}`;
    await page.getByRole("heading", { name: "Nouvelle tâche" }).locator("..")
      .getByLabel("Titre").fill(title);
    await page.getByRole("button", { name: "Créer la tâche" }).click();
    await expect(page.getByText("Tâche créée.")).toBeVisible();
    const task = page.getByRole("listitem").filter({ hasText: title });
    await expect(task).toBeVisible();
    await task.getByRole("button", { name: "Terminer" }).click();
    await expect(page.getByText("Tâche terminée.")).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: title })).toContainText("completed");
  });

  test("8. refuse les mutations CRM à un viewer", async ({ page }) => {
    await login(page, VIEWER_EMAIL!, VIEWER_PASSWORD!);
    await page.goto("/dashboard/crm");
    await expect(page.getByRole("heading", { name: "Prospects", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Nouveau prospect" })).toHaveCount(0);
    const response = await page.request.post("/api/crm/contacts", {
      data: { last_name: "Forbidden Prospect" },
    });
    expect(response.status()).toBe(403);
  });

  test("9. conserve les changements après rafraîchissement", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto(`/dashboard/crm/leads/${SEEDED_LEAD_ID}`);
    await page.reload();
    await expect(page.getByText("Qualifié", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Statut modifié", { exact: true }).first()).toBeVisible();
  });

  test("10. ne révèle aucune donnée d’un autre tenant", async ({ page }) => {
    await login(page, OWNER_EMAIL!, OWNER_PASSWORD!);
    await page.goto(`/dashboard/crm/leads/${FOREIGN_LEAD_ID}`);
    await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
    await expect(page.getByText("Foreign confidential opportunity")).toHaveCount(0);
    await expect(page.getByText("Foreign Prospect")).toHaveCount(0);
  });
});
