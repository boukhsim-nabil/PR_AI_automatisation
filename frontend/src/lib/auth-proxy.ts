import { NextResponse } from "next/server";

import { ACCESS_TOKEN_COOKIE } from "@/lib/auth";


export const REFRESH_COOKIE = "automation_refresh_token";
export const CSRF_COOKIE = "automation_csrf_token";

export function backendAuthUrl(path: string): string {
  const baseUrl = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";
  return `${baseUrl.replace(/\/$/, "")}/v1/auth/${path}`;
}

export function isSafeCookieRequest(request: Request): boolean {
  const origin = request.headers.get("origin");
  const fetchSite = request.headers.get("sec-fetch-site");
  if (fetchSite && fetchSite !== "same-origin" && fetchSite !== "none") return false;
  if (origin) {
    const host = request.headers.get("host");
    if (!host) return false;
    try {
      if (new URL(origin).host !== host) return false;
    } catch {
      return false;
    }
  }
  return true;
}

export function cookieAuthHeaders(request: Request): Headers {
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token") ?? readCookie(cookie, CSRF_COOKIE);
  if (cookie) headers.set("cookie", cookie);
  if (csrf) headers.set("x-csrf-token", csrf);
  return headers;
}

function readCookie(cookieHeader: string | null, name: string): string | null {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return null;
}

export function forwardSessionCookies(
  backendResponse: Response,
  frontendResponse: NextResponse,
): void {
  const headers = backendResponse.headers as Headers & {
    getSetCookie?: () => string[];
  };
  const values = headers.getSetCookie?.() ?? [];
  if (values.length === 0) {
    const combined = backendResponse.headers.get("set-cookie");
    if (combined) values.push(combined);
  }
  for (const value of values) {
    frontendResponse.headers.append(
      "set-cookie",
      value.replace(/Path=\/v1\/auth/gi, "Path=/api/auth"),
    );
  }
}

export function setAccessCookie(
  response: NextResponse,
  accessToken: string,
  expiresIn: number,
): void {
  response.cookies.set(ACCESS_TOKEN_COOKIE, accessToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: Math.max(60, Math.min(expiresIn, 60 * 60)),
    path: "/",
    priority: "high",
  });
}

export function clearFrontendSessionCookies(response: NextResponse): void {
  for (const name of [REFRESH_COOKIE, CSRF_COOKIE]) {
    response.cookies.set(name, "", {
      expires: new Date(0),
      maxAge: 0,
      path: "/api/auth",
    });
  }
}
