"use client";

import { FormEvent, useEffect, useState } from "react";

type Validation = {
  valid: boolean;
  company_name?: string;
  email?: string;
  existing_user?: boolean;
};

export function AcceptInvitationForm({ token }: { token: string }) {
  const [validation, setValidation] = useState<Validation | null>(null);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    fetch(`/api/invitations/validate?token=${encodeURIComponent(token)}`)
      .then((response) => response.json())
      .then(setValidation)
      .catch(() => setValidation({ valid: false }));
  }, [token]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage("");
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const response = await fetch("/api/invitations/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token,
        first_name: data.first_name || null,
        last_name: data.last_name || null,
        password: data.password,
        password_confirmation: data.password_confirmation,
        accept_terms: data.accept_terms === "on",
      }),
    }).catch(() => null);
    if (!response?.ok) {
      setMessage("Cette invitation ne peut pas être acceptée.");
      setPending(false);
      return;
    }
    setMessage("Invitation acceptée. Vous pouvez maintenant vous connecter.");
  }

  if (validation === null) return <p role="status">Vérification de l’invitation…</p>;
  if (!validation.valid) return <p role="alert">Cette invitation est invalide ou expirée.</p>;
  return (
    <form onSubmit={submit} className="mt-6 space-y-4">
      <p className="rounded-xl bg-teal-50 p-4 text-sm text-teal-900">
        Invitation pour {validation.email} — {validation.company_name}
      </p>
      {!validation.existing_user ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <label>Prénom<input name="first_name" required className="mt-1 w-full rounded-lg border p-3" /></label>
          <label>Nom<input name="last_name" required className="mt-1 w-full rounded-lg border p-3" /></label>
        </div>
      ) : null}
      <label className="block">{validation.existing_user ? "Mot de passe actuel" : "Créer un mot de passe"}<input name="password" type="password" required minLength={12} className="mt-1 w-full rounded-lg border p-3" /></label>
      {!validation.existing_user ? <label className="block">Confirmer le mot de passe<input name="password_confirmation" type="password" required minLength={12} className="mt-1 w-full rounded-lg border p-3" /></label> : null}
      {!validation.existing_user ? <label className="flex gap-2"><input name="accept_terms" type="checkbox" required /> J’accepte les conditions d’utilisation.</label> : null}
      {message ? <p role="status">{message}</p> : null}
      <button disabled={pending} className="rounded-xl bg-slate-950 px-5 py-3 font-bold text-white disabled:opacity-60">{pending ? "Validation…" : "Accepter l’invitation"}</button>
    </form>
  );
}
