import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/auth";
import { isSafeCookieRequest } from "@/lib/auth-proxy";
import { PLATFORM_ACCESS_COOKIE } from "@/lib/platform";

export async function POST(request: Request) {
  if (!isSafeCookieRequest(request)) {
    return NextResponse.json({ message: "Requête refusée." }, { status: 403 });
  }
  const token = request.headers
    .get("cookie")
    ?.split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${PLATFORM_ACCESS_COOKIE}=`))
    ?.split("=")
    .slice(1)
    .join("=");
  if (token) {
    await fetch(backendUrl("/v1/platform-auth/logout"), {
      method: "POST",
      headers: { Authorization: `Bearer ${decodeURIComponent(token)}` },
      cache: "no-store",
    }).catch(() => undefined);
  }
  const response = NextResponse.redirect(
    new URL("/admin/login", request.headers.get("origin") ?? request.url),
    303,
  );
  response.cookies.set(PLATFORM_ACCESS_COOKIE, "", {
    expires: new Date(0),
    maxAge: 0,
    path: "/",
  });
  return response;
}
