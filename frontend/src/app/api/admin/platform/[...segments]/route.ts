import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/auth";
import { isSafeCookieRequest } from "@/lib/auth-proxy";
import { PLATFORM_ACCESS_COOKIE } from "@/lib/platform";

async function proxy(
  request: Request,
  context: { params: Promise<{ segments: string[] }> },
) {
  if (request.method !== "GET" && !isSafeCookieRequest(request)) {
    return NextResponse.json({ detail: "Requête refusée." }, { status: 403 });
  }
  const token = request.headers
    .get("cookie")
    ?.split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${PLATFORM_ACCESS_COOKIE}=`))
    ?.split("=")
    .slice(1)
    .join("=");
  if (!token) return NextResponse.json({ detail: "Non authentifié." }, { status: 401 });

  const { segments } = await context.params;
  const source = new URL(request.url);
  const target = new URL(
    backendUrl(`/v1/platform/${segments.map(encodeURIComponent).join("/")}`),
  );
  target.search = source.search;
  const headers = new Headers({ Authorization: `Bearer ${decodeURIComponent(token)}` });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const backend = await fetch(target, {
    method: request.method,
    headers,
    body: request.method === "GET" ? undefined : await request.text(),
    cache: "no-store",
  });
  return new NextResponse(await backend.text(), {
    status: backend.status,
    headers: { "content-type": backend.headers.get("content-type") ?? "application/json" },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
