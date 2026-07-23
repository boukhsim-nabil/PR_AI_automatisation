import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const OWNER_EMAIL = process.env.E2E_EMAIL;
const OWNER_PASSWORD = process.env.E2E_PASSWORD;
const SEEDED_LEAD_ID = "88888888-8888-4888-8888-888888888888";

async function login(page: Page) {
  if (!OWNER_EMAIL || !OWNER_PASSWORD) {
    throw new Error("CRM E2E owner identity is not configured");
  }
  await page.goto("/login");
  await page.getByLabel("Adresse email").fill(OWNER_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL("/dashboard", { timeout: 15_000 });
}

async function expectNoSeriousAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const violations = results.violations.filter(
    (violation) => violation.impact === "critical" || violation.impact === "serious",
  );
  expect(
    violations,
    violations
      .map(
        (violation) =>
          `${violation.id}: ${violation.help}\n${violation.nodes
            .map((node) => node.target.join(" "))
            .join("\n")}`,
      )
      .join("\n\n"),
  ).toEqual([]);
}

test("accessibilité de la connexion", async ({ page }) => {
  await page.goto("/login");
  await expectNoSeriousAccessibilityViolations(page);
});

for (const [name, path] of [
  ["dashboard", "/dashboard"],
  ["CRM", "/dashboard/crm"],
  ["création prospect", "/dashboard/crm/leads/new"],
  ["fiche prospect", `/dashboard/crm/leads/${SEEDED_LEAD_ID}`],
] as const) {
  test(`accessibilité ${name}`, async ({ page }) => {
    await login(page);
    await page.goto(path);
    await expectNoSeriousAccessibilityViolations(page);
  });
}
