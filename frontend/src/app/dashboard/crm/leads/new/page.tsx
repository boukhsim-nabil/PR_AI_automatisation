import Link from "next/link";

import { NewLeadForm } from "@/app/dashboard/crm/leads/new/new-lead-form";
import { requireAuthContext } from "@/lib/auth";

export default async function NewLeadPage() {
  const auth = await requireAuthContext();
  if (!auth.permissions.includes("crm.create")) {
    return (
      <section className="rounded-3xl border border-rose-200 bg-rose-50 p-8" role="alert">
        <h1 className="text-2xl font-bold text-rose-950">Création non autorisée</h1>
        <Link className="secondary-button mt-5" href="/dashboard/crm">Retour au CRM</Link>
      </section>
    );
  }
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <Link className="text-sm font-semibold text-teal-700 hover:underline" href="/dashboard/crm">← Retour au CRM</Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight text-slate-950">Nouveau prospect</h1>
        <p className="mt-2 text-sm text-slate-600">Créez le contact puis sa première opportunité. L’entreprise est déterminée par votre session sécurisée.</p>
      </header>
      <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-8">
        <NewLeadForm />
      </section>
    </div>
  );
}
