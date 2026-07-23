import Link from "next/link";

import { requireAuthContext } from "@/lib/auth";
import { crmGet } from "@/lib/crm-server";
import {
  CrmSummary,
  LeadPage,
  LeadPriority,
  LeadStatus,
  priorityLabels,
  statusLabels,
} from "@/lib/crm";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function value(input: string | string[] | undefined): string {
  return typeof input === "string" ? input : "";
}

function positivePage(input: string): number {
  const parsed = Number.parseInt(input, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

function pageHref(params: URLSearchParams, page: number): string {
  const next = new URLSearchParams(params);
  next.set("page", String(page));
  return `/dashboard/crm?${next}`;
}

function StatusBadge({ status }: { status: LeadStatus }) {
  const tone =
    status === "won"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : status === "lost" || status === "archived"
        ? "bg-slate-100 text-slate-600 ring-slate-200"
        : status === "qualified" || status === "appointment_scheduled"
          ? "bg-sky-50 text-sky-700 ring-sky-200"
          : "bg-amber-50 text-amber-800 ring-amber-200";
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${tone}`}>
      {statusLabels[status]}
    </span>
  );
}

export default async function CrmPage({ searchParams }: { searchParams: SearchParams }) {
  const auth = await requireAuthContext();
  if (!auth.permissions.includes("crm.read")) {
    return (
      <section className="rounded-3xl border border-rose-200 bg-rose-50 p-8" role="alert">
        <h1 className="text-2xl font-bold text-rose-950">Accès CRM refusé</h1>
        <p className="mt-2 text-rose-800">Votre rôle ne permet pas de consulter les prospects.</p>
      </section>
    );
  }

  const raw = await searchParams;
  const search = value(raw.search);
  const selectedStatus = value(raw.status);
  const selectedPriority = value(raw.priority);
  const selectedSource = value(raw.source);
  const page = positivePage(value(raw.page));
  const query = new URLSearchParams({ page: String(page), page_size: "20" });
  if (search) query.set("search", search);
  if (selectedStatus) query.set("status", selectedStatus);
  if (selectedPriority) query.set("priority", selectedPriority);
  if (selectedSource) query.set("source", selectedSource);

  const [summary, leads] = await Promise.all([
    crmGet<CrmSummary>("summary"),
    crmGet<LeadPage>(`leads?${query}`),
  ]);
  const loadError = !summary || !leads;
  const metrics = [
    ["Total prospects", summary?.total_leads ?? 0],
    ["Nouveaux", summary?.new_leads ?? 0],
    ["Qualifiés", summary?.qualified_leads ?? 0],
    ["Gagnés", summary?.won_leads ?? 0],
    ["Tâches en retard", summary?.overdue_tasks ?? 0],
  ];

  return (
    <div className="space-y-7">
      <header className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-700">CRM opérationnel</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">
            Prospects
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Suivez le pipeline commercial de {auth.company.name}, les tâches et les prochaines actions.
          </p>
        </div>
        {auth.permissions.includes("crm.create") ? (
          <Link className="primary-button justify-center" href="/dashboard/crm/leads/new">
            Nouveau prospect
          </Link>
        ) : null}
      </header>

      <section aria-label="Indicateurs CRM" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {metrics.map(([label, metric]) => (
          <article key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
            <p className="mt-2 text-3xl font-bold text-slate-950">{metric}</p>
          </article>
        ))}
      </section>

      <section aria-labelledby="lead-list-title" className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 p-5 sm:p-6">
          <h2 id="lead-list-title" className="text-lg font-bold text-slate-950">Pipeline</h2>
          <p className="mt-1 text-sm text-slate-500">{leads?.total ?? 0} résultat(s)</p>
          <form method="get" className="mt-5 grid gap-3 lg:grid-cols-[minmax(0,1fr)_170px_150px_150px_auto]">
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              <span className="sr-only">Rechercher</span>
              <input className="crm-input" type="search" name="search" defaultValue={search} placeholder="Nom, email, téléphone…" />
            </label>
            <label>
              <span className="sr-only">Statut</span>
              <select className="crm-input" name="status" defaultValue={selectedStatus}>
                <option value="">Tous les statuts</option>
                {(Object.entries(statusLabels) as Array<[LeadStatus, string]>).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Priorité</span>
              <select className="crm-input" name="priority" defaultValue={selectedPriority}>
                <option value="">Toutes priorités</option>
                {(Object.entries(priorityLabels) as Array<[LeadPriority, string]>).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Source</span>
              <select className="crm-input" name="source" defaultValue={selectedSource}>
                <option value="">Toutes sources</option>
                <option value="manual">Manuel</option>
                <option value="form">Formulaire</option>
                <option value="email">Email</option>
                <option value="whatsapp">WhatsApp</option>
                <option value="referral">Recommandation</option>
                <option value="api">API</option>
              </select>
            </label>
            <button className="secondary-button justify-center" type="submit">Filtrer</button>
          </form>
        </div>

        {loadError ? (
          <div className="p-8 text-center" role="alert">
            <h3 className="font-bold text-rose-800">Impossible de charger le CRM</h3>
            <p className="mt-2 text-sm text-slate-600">Réessayez dans quelques instants.</p>
          </div>
        ) : leads.items.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-lg font-bold text-slate-900">Aucun prospect trouvé</p>
            <p className="mt-2 text-sm text-slate-500">Modifiez les filtres ou créez un prospect.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-5 py-3 font-semibold sm:px-6" scope="col">Prospect</th>
                  <th className="px-4 py-3 font-semibold" scope="col">Statut</th>
                  <th className="px-4 py-3 font-semibold" scope="col">Priorité</th>
                  <th className="px-4 py-3 font-semibold" scope="col">Score</th>
                  <th className="px-4 py-3 font-semibold" scope="col">Prochaine action</th>
                  <th className="px-5 py-3 text-right font-semibold sm:px-6" scope="col">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {leads.items.map((lead) => (
                  <tr key={lead.id} className="hover:bg-slate-50/70">
                    <td className="px-5 py-4 sm:px-6">
                      <p className="font-semibold text-slate-900">{[lead.contact_first_name, lead.contact_last_name].filter(Boolean).join(" ")}</p>
                      <p className="mt-1 max-w-xs truncate text-xs text-slate-500">{lead.organization_name ?? lead.contact_email ?? lead.title}</p>
                    </td>
                    <td className="px-4 py-4"><StatusBadge status={lead.status} /></td>
                    <td className="px-4 py-4 font-medium text-slate-700">{priorityLabels[lead.priority]}</td>
                    <td className="px-4 py-4 font-mono font-semibold text-slate-700">{lead.score}</td>
                    <td className="px-4 py-4 text-slate-600">{lead.next_action ?? "À définir"}</td>
                    <td className="px-5 py-4 text-right sm:px-6">
                      <Link className="rounded-lg font-semibold text-teal-700 underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-teal-700" href={`/dashboard/crm/leads/${lead.id}`}>
                        Ouvrir<span className="sr-only"> {lead.contact_first_name} {lead.contact_last_name}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {leads && leads.pages > 1 ? (
          <nav aria-label="Pagination des prospects" className="flex items-center justify-between border-t border-slate-100 px-5 py-4 sm:px-6">
            <Link className={`secondary-button ${page <= 1 ? "pointer-events-none opacity-50" : ""}`} aria-disabled={page <= 1} href={pageHref(query, Math.max(1, page - 1))}>Précédent</Link>
            <span className="text-sm text-slate-500">Page {page} sur {leads.pages}</span>
            <Link className={`secondary-button ${page >= leads.pages ? "pointer-events-none opacity-50" : ""}`} aria-disabled={page >= leads.pages} href={pageHref(query, Math.min(leads.pages, page + 1))}>Suivant</Link>
          </nav>
        ) : null}
      </section>
    </div>
  );
}
