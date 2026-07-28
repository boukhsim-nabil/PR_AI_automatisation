import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { backendUrl } from "@/lib/auth";

export const PLATFORM_ACCESS_COOKIE = "automation_platform_access_token";

export type PlatformCompany = {
  id: string;
  name: string;
  legal_name: string | null;
  slug: string;
  sector: string | null;
  country: string;
  timezone: string;
  language: string;
  currency: string;
  status: string;
  onboarding_status: string;
  plan_code: string;
  trial_ends_at: string | null;
  owner_email: string | null;
  created_at: string;
  suspended_at: string | null;
  suspension_reason: string | null;
};

export async function platformBackendFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const token = (await cookies()).get(PLATFORM_ACCESS_COOKIE)?.value;
  if (!token) redirect("/admin/login");
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(backendUrl(path), { ...init, headers, cache: "no-store" });
}

export async function requirePlatformAdmin(): Promise<{
  user: { id: string; email: string; display_name: string | null };
  platform_role: string;
}> {
  const response = await platformBackendFetch("/v1/platform-auth/me");
  if (!response.ok) redirect("/admin/login");
  return response.json();
}
