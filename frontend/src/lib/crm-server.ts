import "server-only";

import { redirect } from "next/navigation";

import { authenticatedBackendFetch } from "@/lib/auth";
import { ApiError, apiErrorFromResponse } from "@/lib/api-error";

export async function crmGet<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await authenticatedBackendFetch(`/v1/crm/${path}`);
  } catch {
    throw new ApiError(503, "technical", "CRM service unavailable");
  }
  if (response.status === 401) {
    redirect("/session/refresh?returnTo=/dashboard/crm");
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return (await response.json()) as T;
}
