import "server-only";

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ACCESS_TOKEN_COOKIE, backendUrl } from "@/lib/auth";
import { isSafeCookieRequest } from "@/lib/auth-proxy";

export async function proxyCrmRequest(
  request: Request,
  backendPath: string,
): Promise<NextResponse> {
  if (request.method !== "GET" && !isSafeCookieRequest(request)) {
    return NextResponse.json({ detail: "Cross-site request rejected" }, { status: 403 });
  }

  const token = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  }

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const body = request.method === "GET" ? undefined : await request.text();

  try {
    const backendResponse = await fetch(backendUrl(backendPath), {
      method: request.method,
      headers,
      body,
      cache: "no-store",
    });
    const responseHeaders = new Headers();
    const responseContentType = backendResponse.headers.get("content-type");
    const correlationId = backendResponse.headers.get("x-correlation-id");
    if (responseContentType) responseHeaders.set("content-type", responseContentType);
    if (correlationId) responseHeaders.set("x-correlation-id", correlationId);
    return new NextResponse(await backendResponse.arrayBuffer(), {
      status: backendResponse.status,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json({ detail: "CRM service unavailable" }, { status: 503 });
  }
}
