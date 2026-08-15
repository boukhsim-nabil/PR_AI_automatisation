import {
  expect,
  request,
  type APIRequestContext,
} from "@playwright/test";

export type TenantCredentials = {
  email: string;
  password: string;
  companyId: string;
};

type LoginResponse = { access_token: string };

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required for Inbox API tests`);
  }
  return value;
}

export function e2eIdentities() {
  return {
    ownerA: {
      email: required("E2E_EMAIL"),
      password: required("E2E_PASSWORD"),
      companyId: required("E2E_COMPANY_ID"),
    },
    supportA: {
      email: required("E2E_SUPPORT_EMAIL"),
      password: required("E2E_SUPPORT_PASSWORD"),
      companyId: required("E2E_COMPANY_ID"),
    },
    viewerA: {
      email: required("E2E_VIEWER_EMAIL"),
      password: required("E2E_VIEWER_PASSWORD"),
      companyId: required("E2E_COMPANY_ID"),
    },
    inboxReaderA: {
      email: required("E2E_INBOX_READER_EMAIL"),
      password: required("E2E_INBOX_READER_PASSWORD"),
      companyId: required("E2E_COMPANY_ID"),
    },
    ownerB: {
      email: required("E2E_FOREIGN_EMAIL"),
      password: required("E2E_FOREIGN_PASSWORD"),
      companyId: required("E2E_FOREIGN_COMPANY_ID"),
    },
  } satisfies Record<string, TenantCredentials>;
}

async function login(api: APIRequestContext, credentials: TenantCredentials): Promise<string> {
  const response = await api.post("/v1/auth/login", {
    data: {
      email: credentials.email,
      password: credentials.password,
      company_id: credentials.companyId,
    },
  });
  expect(response.status(), "Synthetic E2E login must succeed").toBe(200);
  const payload = (await response.json()) as LoginResponse;
  expect(payload.access_token).toBeTruthy();
  return payload.access_token;
}

export async function authenticatedApi(
  requestFactory: typeof request,
  credentials: TenantCredentials,
): Promise<APIRequestContext> {
  const baseURL = process.env.API_BASE_URL ?? "http://localhost:8000";
  const loginContext = await requestFactory.newContext({ baseURL });
  try {
    const accessToken = await login(loginContext, credentials);
    return await requestFactory.newContext({
      baseURL,
      extraHTTPHeaders: { Authorization: `Bearer ${accessToken}` },
    });
  } finally {
    await loginContext.dispose();
  }
}
