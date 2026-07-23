import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export const ACCESS_TOKEN_COOKIE = "automation_access_token";

export type AuthContext = {
  user: {
    id: string;
    email: string;
    display_name: string | null;
  };
  company: {
    id: string;
    name: string;
  };
  membership: {
    id: string;
    status: string;
  };
  role: {
    id: string;
    code: string;
    name: string;
  } | null;
  permissions: string[];
};

export function backendUrl(path: string): string {
  const baseUrl = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

export async function authenticatedBackendFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const token = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!token) {
    redirect("/session/refresh?returnTo=/dashboard/crm");
  }
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(backendUrl(path), { ...init, headers, cache: "no-store" });
}

export async function requireAuthContext(): Promise<AuthContext> {
  const token = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!token) {
    redirect("/session/refresh?returnTo=/dashboard");
  }

  let response: Response;
  try {
    response = await fetch(backendUrl("/v1/auth/me"), {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    redirect("/login");
  }
  if (!response.ok) {
    redirect("/session/refresh?returnTo=/dashboard");
  }
  return (await response.json()) as AuthContext;
}
