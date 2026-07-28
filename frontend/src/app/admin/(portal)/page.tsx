import Link from "next/link";

import { platformBackendFetch } from "@/lib/platform";

type Summary = {
  total_companies: number;
  active_companies: number;
  onboarding_companies: number;
  suspended_companies: number;
  pending_owner_invitations: number;
  trials_expiring_soon: number;
};

export default async function AdminPage() {
  const response = await platformBackendFetch("/v1/platform/summary");
  if (!response.ok) throw new Error("Impossible de charger le résumé plateforme.");
  const summary = (await response.json()) as Summary;
  const cards = [
    ["Entreprises", summary.total_companies],
    ["Actives", summary.active_companies],
    ["En onboarding", summary.onboarding_companies],
    ["Suspendues", summary.suspended_companies],
    ["Invitations en attente", summary.pending_owner_invitations],
    ["Essais à échéance", summary.trials_expiring_soon],
  ];
  return (
    <>
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-sm font-bold uppercase tracking-wider text-teal-700">Plateforme</p>
          <h1 className="mt-2 text-3xl font-bold">Vue d’ensemble</h1>
        </div>
        <Link href="/admin/companies/new" className="rounded-xl bg-slate-950 px-4 py-3 text-sm font-bold text-white">
          Nouvelle entreprise
        </Link>
      </div>
      <section aria-label="Indicateurs" className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map(([label, value]) => (
          <article key={label} className="rounded-2xl border border-slate-200 bg-white p-6">
            <p className="text-sm text-slate-600">{label}</p>
            <p className="mt-2 text-3xl font-bold">{value}</p>
          </article>
        ))}
      </section>
    </>
  );
}
