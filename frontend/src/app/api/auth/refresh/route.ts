import { NextResponse } from "next/server";

import {
  backendAuthUrl,
  cookieAuthHeaders,
  forwardSessionCookies,
  isSafeCookieRequest,
  setAccessCookie,
} from "@/lib/auth-proxy";


type RefreshResponse = { access_token: string; expires_in: number };

export async function POST(request: Request) {
  if (!isSafeCookieRequest(request)) {
    return NextResponse.json({ authenticated: false }, { status: 403 });
  }
  try {
    const backendResponse = await fetch(backendAuthUrl("refresh"), {
      method: "POST",
      headers: cookieAuthHeaders(request),
      cache: "no-store",
    });
    if (!backendResponse.ok) {
      const response = NextResponse.json(
        { authenticated: false },
        { status: backendResponse.status },
      );
      forwardSessionCookies(backendResponse, response);
      return response;
    }
    const auth = (await backendResponse.json()) as RefreshResponse;
    const response = NextResponse.json({ authenticated: true });
    setAccessCookie(response, auth.access_token, auth.expires_in);
    forwardSessionCookies(backendResponse, response);
    return response;
  } catch {
    return NextResponse.json({ authenticated: false }, { status: 503 });
  }
}
