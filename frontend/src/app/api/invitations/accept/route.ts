import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/auth";
import { isSafeCookieRequest } from "@/lib/auth-proxy";

export async function POST(request: Request) {
  if (!isSafeCookieRequest(request)) {
    return NextResponse.json({ detail: "Requête refusée." }, { status: 403 });
  }
  const response = await fetch(backendUrl("/v1/invitations/accept"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
