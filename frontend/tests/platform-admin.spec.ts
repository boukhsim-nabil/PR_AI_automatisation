import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const ADMIN_EMAIL = "e2e-platform-admin@example.com";
const ADMIN_PASSWORD = process.env.E2E_PLATFORM_ADMIN_PASSWORD;
const TENANT_OWNER_EMAIL = process.env.E2E_EMAIL;
const TENANT_OWNER_PASSWORD = process.env.E2E_PASSWORD;
const BACKEND = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

test.beforeAll(() => {
  if (!ADMIN_PASSWORD || !TENANT_OWNER_EMAIL || !TENANT_OWNER_PASSWORD) {
    throw new Error("Platform and tenant synthetic E2E identities are required");
  }
});

async function loginPlatform(page: import("@playwright/test").Page) {
  await page.goto("/admin/login");
  await page.getByLabel("Adresse email").fill(ADMIN_EMAIL);
  await page.getByLabel("Mot de passe").fill(ADMIN_PASSWORD!);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL("/admin", { timeout: 15_000 });
}

async function invitationToken(invitationId: string): Promise<string> {
  const file = path.resolve(
    process.cwd(),
    "..",
    ".local",
    "emails",
    `${invitationId}.json`,
  );
  const message = JSON.parse(await readFile(file, "utf8")) as { accept_url: string };
  return new URL(message.accept_url).searchParams.get("token") ?? "";
}

test("refuse le portail sans session et avec une session tenant", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL("/admin/login");

  await page.goto("/login");
  await page.getByLabel("Adresse email").fill(TENANT_OWNER_EMAIL!);
  await page.getByLabel("Mot de passe", { exact: true }).fill(TENANT_OWNER_PASSWORD!);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL("/dashboard", { timeout: 15_000 });
  await page.goto("/admin");
  await expect(page).toHaveURL("/admin/login");
});

test("provisionne, invite, suspend et réactive sans exposer de token", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  await loginPlatform(page);
  await expect(page.getByRole("heading", { name: "Vue d’ensemble" })).toBeVisible();
  await page.getByRole("link", { name: "Entreprises" }).click();
  await expect(page.getByRole("heading", { name: "Entreprises clientes" })).toBeVisible();

  const unique = Date.now().toString();
  const companyName = `E2E Atlas ${unique}`;
  const ownerEmail = `owner-${unique}@example.com`;
  const ownerPassword = "Owner-E2E-Invitation!7qR4";
  await page.getByRole("link", { name: "Créer un client" }).click();
  await page.getByLabel("Nom commercial").fill(companyName);
  await page.getByLabel("Secteur").fill("Services");
  await page.getByLabel("Prénom du futur Owner").fill("Nadia");
  await page.getByLabel("Nom du futur Owner", { exact: true }).fill("E2E");
  await page.getByLabel("Email du futur Owner").fill(ownerEmail);
  const creationResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/admin/platform/companies") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Créer l’entreprise et l’invitation" }).click();
  const creation = await creationResponse;
  expect(creation.status()).toBe(201);
  const created = (await creation.json()) as {
    company: { id: string };
    invitation: { id: string };
  };
  const companyId = created.company.id;
  await page.goto(`/admin/companies/${companyId}`);
  await expect(page.getByRole("heading", { name: companyName })).toBeVisible();
  const dom = await page.locator("body").innerText();
  expect(dom).not.toContain("token=");

  const invitations = await page.request.get(
    `/api/admin/platform/companies/${companyId}/invitations`,
  );
  expect(invitations.status()).toBe(200);
  const invitation = (await invitations.json())[0] as { id: string };
  expect(invitation.id).toBe(created.invitation.id);
  const rawToken = await invitationToken(invitation.id);
  expect(rawToken.length).toBeGreaterThan(32);

  await page.goto(`/invitations/accept?token=${encodeURIComponent(rawToken)}`);
  await page.getByLabel("Prénom").fill("Nadia");
  await page.getByLabel("Nom", { exact: true }).fill("E2E");
  await page.getByLabel("Créer un mot de passe").fill(ownerPassword);
  await page.getByLabel("Confirmer le mot de passe").fill(ownerPassword);
  await page.getByLabel(/J’accepte/).check();
  await page.getByRole("button", { name: "Accepter l’invitation" }).click();
  await expect(page.getByRole("status")).toContainText("Invitation acceptée");

  let tenantLogin = await request.post(`${BACKEND}/v1/auth/login`, {
    data: { email: ownerEmail, password: ownerPassword, company_id: companyId },
  });
  expect(tenantLogin.status()).toBe(200);

  await loginPlatform(page);
  await page.goto(`/admin/companies/${companyId}`);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByLabel("Motif obligatoire").fill("Suspension contrôlée E2E");
  await page.getByRole("button", { name: "Suspendre" }).click();
  await expect(page.getByText("suspended", { exact: true })).toBeVisible();
  tenantLogin = await request.post(`${BACKEND}/v1/auth/login`, {
    data: { email: ownerEmail, password: ownerPassword, company_id: companyId },
  });
  expect(tenantLogin.status()).toBe(401);

  await page.getByRole("button", { name: "Réactiver l’entreprise" }).click();
  await expect(page.getByText("onboarding", { exact: true })).toBeVisible();
  tenantLogin = await request.post(`${BACKEND}/v1/auth/login`, {
    data: { email: ownerEmail, password: ownerPassword, company_id: companyId },
  });
  expect(tenantLogin.status()).toBe(200);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: companyName })).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations.filter(
      (violation) => violation.impact === "critical" || violation.impact === "serious",
    ),
  ).toEqual([]);
  const cookies = await page.context().cookies();
  expect(cookies.find((cookie) => cookie.name === "automation_platform_access_token")?.httpOnly).toBe(
    true,
  );
  expect((await readdir(path.resolve(process.cwd(), "..", ".local", "emails"))).length).toBeGreaterThan(0);
});
