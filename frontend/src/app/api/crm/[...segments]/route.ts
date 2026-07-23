import { proxyCrmRequest } from "@/lib/crm-proxy";

type RouteContext = { params: Promise<{ segments: string[] }> };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const COLLECTIONS = new Set(["summary", "assignees", "contacts", "leads", "tasks"]);
const ACTIONS = new Set(["archive", "assign", "status", "activities", "complete"]);
const QUERY_PARAMETERS = new Set([
  "search",
  "status",
  "priority",
  "source",
  "assigned_membership_id",
  "lead_id",
  "contact_id",
  "created_from",
  "created_to",
  "due_from",
  "due_to",
  "sort_by",
  "sort_direction",
  "page",
  "page_size",
]);

function isAllowedPath(segments: string[]): boolean {
  if (segments.length === 0 || !COLLECTIONS.has(segments[0])) return false;
  if (segments.length === 1) return true;
  if (segments[0] === "leads" && segments[1] === "with-contact" && segments.length === 2) {
    return true;
  }
  if (!UUID_PATTERN.test(segments[1])) return false;
  return segments.length === 2 || (segments.length === 3 && ACTIONS.has(segments[2]));
}

async function forward(request: Request, context: RouteContext) {
  const { segments } = await context.params;
  if (!isAllowedPath(segments)) {
    return Response.json({ detail: "Invalid CRM route" }, { status: 400 });
  }
  const query = new URLSearchParams();
  for (const [key, value] of new URL(request.url).searchParams) {
    if (QUERY_PARAMETERS.has(key)) query.append(key, value);
  }
  const suffix = query.size ? `?${query}` : "";
  return proxyCrmRequest(request, `/v1/crm/${segments.join("/")}${suffix}`);
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
