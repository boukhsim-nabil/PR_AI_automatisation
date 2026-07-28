import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/auth";

export async function GET(request: Request) {
  const token = new URL(request.url).searchParams.get("token") ?? "";
  const response = await fetch(
    `${backendUrl("/v1/invitations/validate")}?token=${encodeURIComponent(token)}`,
    { cache: "no-store" },
  );
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
