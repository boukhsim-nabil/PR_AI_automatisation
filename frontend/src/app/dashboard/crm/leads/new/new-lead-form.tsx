"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type ErrorPayload = { detail?: string | Array<{ msg?: string }> };
type CreatedContact = { id: string };
type CreatedLead = { id: string };

function message(payload: ErrorPayload, status: number): string {
  if (status === 409) return "Un contact utilise déjà cet email dans votre entreprise.";
  if (status === 403) return "Vous n’avez pas la permission de créer ce prospect.";
  if (status === 422) return "Vérifiez les champs signalés puis réessayez.";
  return typeof payload.detail === "string" ? payload.detail : "La création a échoué.";
}

export function NewLeadForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    const form = new FormData(event.currentTarget);

    try {
      const contactResponse = await fetch("/api/crm/contacts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          first_name: form.get("first_name") || null,
          last_name: form.get("last_name"),
          email: form.get("email") || null,
          phone: form.get("phone") || null,
          job_title: form.get("job_title") || null,
          organization_name: form.get("organization_name") || null,
          language: form.get("language"),
          consent_email: form.get("consent_email") === "on",
          consent_whatsapp: form.get("consent_whatsapp") === "on",
        }),
      });
      const contactPayload = (await contactResponse.json().catch(() => ({}))) as
        | CreatedContact
        | ErrorPayload;
      if (!contactResponse.ok || !("id" in contactPayload)) {
        setError(message(contactPayload as ErrorPayload, contactResponse.status));
        return;
      }

      const nextActionAt = String(form.get("next_action_at") || "");
      const budget = String(form.get("estimated_budget") || "").trim();
      const leadResponse = await fetch("/api/crm/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contact_id: contactPayload.id,
          title: form.get("title"),
          need_description: form.get("need_description") || null,
          estimated_budget: budget || null,
          currency: form.get("currency"),
          urgency: form.get("urgency"),
          source: form.get("source"),
          score: Number(form.get("score") || 0),
          priority: form.get("priority"),
          next_action: form.get("next_action") || null,
          next_action_at: nextActionAt ? new Date(nextActionAt).toISOString() : null,
        }),
      });
      const leadPayload = (await leadResponse.json().catch(() => ({}))) as
        | CreatedLead
        | ErrorPayload;
      if (!leadResponse.ok || !("id" in leadPayload)) {
        setError(
          `${message(leadPayload as ErrorPayload, leadResponse.status)} Le contact a été conservé.`,
        );
        return;
      }
      router.push(`/dashboard/crm/leads/${leadPayload.id}`);
      router.refresh();
    } catch {
      setError("Le service CRM est indisponible. Réessayez dans quelques instants.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-8" aria-busy={pending}>
      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="col-span-full mb-2 text-lg font-bold text-slate-950">Contact</legend>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Prénom
          <input className="crm-input" name="first_name" maxLength={120} autoComplete="given-name" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Nom <span className="sr-only">obligatoire</span>
          <input className="crm-input" name="last_name" required maxLength={120} autoComplete="family-name" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Email
          <input className="crm-input" name="email" type="email" maxLength={320} autoComplete="email" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Téléphone
          <input className="crm-input" name="phone" type="tel" maxLength={40} autoComplete="tel" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Fonction
          <input className="crm-input" name="job_title" maxLength={255} />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Organisation
          <input className="crm-input" name="organization_name" maxLength={255} autoComplete="organization" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Langue
          <select className="crm-input" name="language" defaultValue="fr">
            <option value="fr">Français</option>
            <option value="en">Anglais</option>
            <option value="ar">Arabe</option>
          </select>
        </label>
        <div className="grid content-end gap-2 text-sm text-slate-700">
          <label className="flex min-h-8 items-center gap-2"><input type="checkbox" name="consent_email" /> Consentement email</label>
          <label className="flex min-h-8 items-center gap-2"><input type="checkbox" name="consent_whatsapp" /> Consentement WhatsApp</label>
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="col-span-full mb-2 text-lg font-bold text-slate-950">Premier prospect</legend>
        <label className="col-span-full grid gap-1.5 text-sm font-medium text-slate-700">
          Intitulé <span className="sr-only">obligatoire</span>
          <input className="crm-input" name="title" required maxLength={255} />
        </label>
        <label className="col-span-full grid gap-1.5 text-sm font-medium text-slate-700">
          Besoin
          <textarea className="crm-input min-h-28 resize-y" name="need_description" maxLength={4000} />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Budget estimé
          <input className="crm-input" name="estimated_budget" type="number" min="0" step="0.01" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Devise
          <input className="crm-input" name="currency" defaultValue="MAD" pattern="[A-Za-z]{3}" maxLength={3} />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Urgence
          <select className="crm-input" name="urgency" defaultValue="medium">
            <option value="low">Faible</option><option value="medium">Moyenne</option>
            <option value="high">Haute</option><option value="critical">Critique</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Source
          <select className="crm-input" name="source" defaultValue="manual">
            <option value="manual">Manuel</option><option value="form">Formulaire</option>
            <option value="email">Email</option><option value="whatsapp">WhatsApp</option>
            <option value="referral">Recommandation</option><option value="api">API</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Score
          <input className="crm-input" name="score" type="number" min="0" max="100" defaultValue="0" required />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Priorité
          <select className="crm-input" name="priority" defaultValue="medium">
            <option value="low">Faible</option><option value="medium">Moyenne</option><option value="high">Haute</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Prochaine action
          <input className="crm-input" name="next_action" maxLength={500} />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-slate-700">
          Date de prochaine action
          <input className="crm-input" name="next_action_at" type="datetime-local" />
        </label>
      </fieldset>

      <div aria-live="assertive" className="min-h-6 text-sm font-medium text-rose-700">
        {error}
      </div>
      <button className="primary-button justify-center" type="submit" disabled={pending}>
        {pending ? "Création en cours…" : "Créer le contact et le prospect"}
      </button>
    </form>
  );
}
