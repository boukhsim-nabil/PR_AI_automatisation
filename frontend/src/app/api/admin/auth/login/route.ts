import { NextResponse } from "next/server";

import { backendUrl } from "@/lib/auth";
import { isSafeCookieRequest } from "@/lib/auth-proxy";
import { PLATFORM_ACCESS_COOKIE } from "@/lib/platform";

type PlatformToken = {
  access_token: string;
  expires_in: number;
};

export async function POST(request: Request) {
  if (!isSafeCookieRequest(request)) {
    return NextResponse.json({ message: "Requête refusée." }, { status: 403 });
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body.email !== "string" || typeof body.password !== "string") {
    return NextResponse.json({ message: "Identifiants invalides." }, { status: 400 });
  }
  try {
    const backend = await fetch(backendUrl("/v1/platform-auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: body.email, password: body.password }),
      cache: "no-store",
    });
    if (!backend.ok) {
      return NextResponse.json(
        { message: "Connexion impossible. Vérifiez vos informations." },
        { status: backend.status },
      );
    }
    const auth = (await backend.json()) as PlatformToken;
    const response = NextResponse.json({ authenticated: true });
    response.cookies.set(PLATFORM_ACCESS_COOKIE, auth.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      maxAge: Math.max(60, Math.min(auth.expires_in, 600)),
      path: "/",
      priority: "high",
    });
    return response;
  } catch {
    return NextResponse.json({ message: "Service indisponible." }, { status: 503 });
  }
}
