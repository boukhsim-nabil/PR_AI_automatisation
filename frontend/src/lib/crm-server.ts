import "server-only";

import { redirect } from "next/navigation";

import { authenticatedBackendFetch } from "@/lib/auth";

export async function crmGet<T>(path: string): Promise<T | null> {
  const response = await authenticatedBackendFetch(`/v1/crm/${path}`).catch(() => null);
  if (response?.status === 401) {
    redirect("/session/refresh?returnTo=/dashboard/crm");
  }
  if (!response?.ok) return null;
  return (await response.json()) as T;
}
