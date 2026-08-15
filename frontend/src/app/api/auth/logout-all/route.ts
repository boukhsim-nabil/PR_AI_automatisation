import { NextResponse } from "next/server";

import { ACCESS_TOKEN_COOKIE } from "@/lib/auth";
import {
  backendAuthUrl,
  clearFrontendSessionCookies,
  cookieAuthHeaders,
  forwardSessionCookies,
  isSafeCookieRequest,
} from "@/lib/auth-proxy";


export async function POST(request: Request) {
  if (!isSafeCookieRequest(request)) {
    return NextResponse.json({ message: "Requête CSRF refusée." }, { status: 403 });
  }
  let backendResponse: Response | null = null;
  try {
    backendResponse = await fetch(backendAuthUrl("logout-all"), {
      method: "POST",
      headers: cookieAuthHeaders(request),
      cache: "no-store",
    });
  } catch {
    // The browser session is still cleared if the backend is unavailable.
  }
  const response = NextResponse.redirect(
    new URL("/login", request.headers.get("origin") ?? request.url),
    303,
  );
  response.cookies.delete(ACCESS_TOKEN_COOKIE);
  clearFrontendSessionCookies(response);
  if (backendResponse) forwardSessionCookies(backendResponse, response);
  return response;
}
