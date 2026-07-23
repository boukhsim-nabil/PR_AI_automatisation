export type ApiErrorKind =
  | "validation"
  | "authentication"
  | "permission"
  | "not_found"
  | "conflict"
  | "rate_limit"
  | "technical";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly kind: ApiErrorKind,
    message: string,
    public readonly correlationId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function classifyApiStatus(status: number): ApiErrorKind {
  if (status === 400 || status === 422) return "validation";
  if (status === 401) return "authentication";
  if (status === 403) return "permission";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 429) return "rate_limit";
  return "technical";
}

export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const payload = (await response.json().catch(() => ({}))) as {
    detail?: string | Array<{ msg?: string }>;
  };
  const detail =
    typeof payload.detail === "string"
      ? payload.detail
      : payload.detail?.map((item) => item.msg).filter(Boolean).join(", ");
  return new ApiError(
    response.status,
    classifyApiStatus(response.status),
    detail || `La requête a échoué (${response.status}).`,
    response.headers.get("x-correlation-id") ?? undefined,
  );
}

export function userFacingApiError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Le service CRM est indisponible. Réessayez dans quelques instants.";
  }
  switch (error.kind) {
    case "validation":
      return "Vérifiez les champs saisis puis réessayez.";
    case "authentication":
      return "Votre session a expiré. Reconnectez-vous.";
    case "permission":
      return "Vous n’avez pas la permission d’effectuer cette action.";
    case "not_found":
      return "La ressource demandée est introuvable.";
    case "conflict":
      return "Cette opération entre en conflit avec une donnée existante.";
    case "rate_limit":
      return "Trop de requêtes ont été envoyées. Réessayez plus tard.";
    case "technical":
      return "Le service CRM est temporairement indisponible.";
  }
}
