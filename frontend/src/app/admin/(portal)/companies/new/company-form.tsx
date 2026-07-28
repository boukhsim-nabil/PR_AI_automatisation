"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function CompanyForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError("");
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const response = await fetch("/api/admin/platform/companies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...data, trial_days: Number(data.trial_days) }),
    }).catch(() => null);
    if (!response?.ok) {
      const body = await response?.json().catch(() => null);
      setError(body?.detail ?? "La création a échoué.");
      setPending(false);
      return;
    }
    const result = await response.json();
    router.push(`/admin/companies/${result.company.id}?created=1`);
  }

  const fields = [
    ["name", "Nom commercial", "text", true],
    ["legal_name", "Raison sociale", "text", false],
    ["sector", "Secteur", "text", false],
    ["country", "Pays", "text", true, "MA"],
    ["timezone", "Fuseau horaire", "text", true, "Africa/Casablanca"],
    ["language", "Langue", "text", true, "fr"],
    ["currency", "Devise", "text", true, "MAD"],
    ["plan_code", "Plan", "text", true, "trial"],
    ["trial_days", "Durée d’essai (jours)", "number", true, "14"],
    ["owner_first_name", "Prénom du futur Owner", "text", true],
    ["owner_last_name", "Nom du futur Owner", "text", true],
    ["owner_email", "Email du futur Owner", "email", true],
  ] as const;
  return (
    <form onSubmit={submit} className="mt-8 grid gap-5 rounded-2xl border border-slate-200 bg-white p-6 sm:grid-cols-2">
      {fields.map(([name, label, type, required, defaultValue]) => (
        <label key={name} className="text-sm font-semibold text-slate-800">
          {label}
          <input name={name} type={type} required={required} defaultValue={defaultValue} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" />
        </label>
      ))}
      {error ? <p role="alert" className="sm:col-span-2 rounded-lg bg-red-50 p-3 text-red-800">{error}</p> : null}
      <div className="sm:col-span-2">
        <button disabled={pending} className="rounded-xl bg-slate-950 px-5 py-3 font-bold text-white disabled:opacity-60">
          {pending ? "Création…" : "Créer l’entreprise et l’invitation"}
        </button>
      </div>
    </form>
  );
}
