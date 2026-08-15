import { request, type FullConfig } from "@playwright/test";

export default async function globalSetup(config: FullConfig) {
  const marker = process.env.E2E_DATABASE_MARKER;
  if (!marker || !["automation_test", "automation_e2e"].includes(marker)) {
    throw new Error(
      "E2E_DATABASE_MARKER must identify automation_test or automation_e2e; refusing API tests",
    );
  }

  const baseURL = config.projects[0]?.use.baseURL;
  if (typeof baseURL !== "string") {
    throw new Error("API_BASE_URL is required");
  }
  const target = new URL(baseURL);
  const localHost = target.hostname === "localhost" || target.hostname === "127.0.0.1";
  if (!localHost || target.port !== "8000" || target.protocol !== "http:") {
    throw new Error("API tests only accept http://localhost:8000 or http://127.0.0.1:8000");
  }

  const api = await request.newContext({ baseURL });
  try {
    const health = await api.get("/health");
    if (!health.ok()) {
      throw new Error(`Test API health check failed with HTTP ${health.status()}`);
    }
    const payload = (await health.json()) as {
      environment?: string;
      database_marker?: string;
    };
    if (!payload.environment || !["test", "e2e"].includes(payload.environment)) {
      throw new Error(
        "The API did not attest a test/e2e environment; refusing any API test mutation",
      );
    }
    if (payload.database_marker !== marker) {
      throw new Error(
        "The API database does not match E2E_DATABASE_MARKER; refusing any API test mutation",
      );
    }
  } finally {
    await api.dispose();
  }
}
