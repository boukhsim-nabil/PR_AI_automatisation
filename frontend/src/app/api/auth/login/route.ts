import { NextResponse } from "next/server";

import {
  backendAuthUrl,
  forwardSessionCookies,
  setAccessCookie,
} from "@/lib/auth-proxy";

type BackendLoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  company_id: string;
};

const GENERIC_AUTH_ERROR =
  "Connexion impossible. Vérifiez vos informations ou contactez votre administrateur.";

export async function POST(request: Request) {
  let credentials: { email?: unknown; password?: unknown };

  try {
    credentials = (await request.json()) as {
      email?: unknown;
      password?: unknown;
    };
  } catch {
    return NextResponse.json({ message: GENERIC_AUTH_ERROR }, { status: 400 });
  }

  const email =
    typeof credentials.email === "string" ? credentials.email.trim() : "";
  const password =
    typeof credentials.password === "string" ? credentials.password : "";
  const companyId = process.env.DEFAULT_COMPANY_ID;

  if (!email || !password) {
    return NextResponse.json({ message: GENERIC_AUTH_ERROR }, { status: 400 });
  }

  if (!companyId) {
    return NextResponse.json(
      {
        message:
          "Le service de connexion n’est pas configuré. Contactez votre administrateur.",
      },
      { status: 503 },
    );
  }

  try {
    const backendResponse = await fetch(
      backendAuthUrl("login"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.toLowerCase(),
          password,
          company_id: companyId,
        }),
        cache: "no-store",
      },
    );

    if (!backendResponse.ok) {
      const message =
        backendResponse.status === 429
          ? "Trop de tentatives. La connexion est temporairement bloquée ; réessayez plus tard."
          : GENERIC_AUTH_ERROR;
      return NextResponse.json({ message }, { status: backendResponse.status });
    }

    const auth = (await backendResponse.json()) as BackendLoginResponse;
    if (!auth.access_token || !Number.isFinite(auth.expires_in)) {
      throw new Error("Invalid authentication response");
    }

    const response = NextResponse.json({ authenticated: true });
    setAccessCookie(response, auth.access_token, auth.expires_in);
    forwardSessionCookies(backendResponse, response);
    return response;
  } catch {
    return NextResponse.json(
      {
        message:
          "Le service de connexion est indisponible. Votre session n’a pas été ouverte ; réessayez dans quelques instants.",
      },
      { status: 503 },
    );
  }
}
