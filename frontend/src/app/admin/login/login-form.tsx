"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function AdminLoginForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    setLoading(true);
    setError("");
    const data = new FormData(event.currentTarget);
    const response = await fetch("/api/admin/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: data.get("email"),
        password: data.get("password"),
      }),
    }).catch(() => null);
    if (!response?.ok) {
      const payload = await response?.json().catch(() => null);
      setError(payload?.message ?? "Connexion impossible.");
      setLoading(false);
      return;
    }
    router.replace("/admin");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="mt-8 space-y-5">
      <div>
        <label htmlFor="email" className="text-sm font-semibold text-slate-800">
          Adresse email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3"
        />
      </div>
      <div>
        <label htmlFor="password" className="text-sm font-semibold text-slate-800">
          Mot de passe
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3"
        />
      </div>
      {error ? (
        <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-xl bg-slate-950 px-4 py-3 font-semibold text-white disabled:opacity-60"
      >
        {loading ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}
