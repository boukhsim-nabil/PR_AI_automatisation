import { notFound } from "next/navigation";

import { PlatformCompany, platformBackendFetch } from "@/lib/platform";

import { CompanyActions } from "./company-actions";

type Invitation = {
  id: string;
  email: string;
  status: string;
  expires_at: string;
  created_at: string;
};
type Usage = { contacts: number; leads: number; tasks: number; sessions_active: number };

export default async function CompanyDetails({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [companyResponse, invitationsResponse, usageResponse] = await Promise.all([
    platformBackendFetch(`/v1/platform/companies/${id}`),
    platformBackendFetch(`/v1/platform/companies/${id}/invitations`),
    platformBackendFetch(`/v1/platform/companies/${id}/usage-summary`),
  ]);
  if (companyResponse.status === 404) notFound();
  if (!companyResponse.ok) throw new Error("Impossible de charger l’entreprise.");
  const company = (await companyResponse.json()) as PlatformCompany;
  const invitations = invitationsResponse.ok ? ((await invitationsResponse.json()) as Invitation[]) : [];
  const usage = usageResponse.ok ? ((await usageResponse.json()) as Usage) : null;
  return (
    <>
      <div>
        <p className="text-sm font-bold uppercase tracking-wider text-teal-700">{company.slug}</p>
        <h1 className="mt-2 text-3xl font-bold">{company.name}</h1>
        <p className="mt-2 text-slate-600">{company.legal_name ?? "Raison sociale non renseignée"}</p>
      </div>
      <section className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Informations entreprise">
        {[["Statut", company.status], ["Plan", company.plan_code], ["Onboarding", company.onboarding_status], ["Owner", company.owner_email ?? "Invitation en attente"]].map(([label, value]) => (
          <article key={label} className="rounded-2xl border border-slate-200 bg-white p-5"><p className="text-sm text-slate-600">{label}</p><p className="mt-2 font-bold">{value}</p></article>
        ))}
      </section>
      {usage ? <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6"><h2 className="text-xl font-bold">Consommation sommaire</h2><p className="mt-3 text-sm text-slate-700">{usage.contacts} contacts · {usage.leads} prospects · {usage.tasks} tâches · {usage.sessions_active} session(s) active(s)</p></section> : null}
      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
        <h2 className="text-xl font-bold">Invitations Owner</h2>
        {invitations.length ? <ul className="mt-4 divide-y divide-slate-100">{invitations.map((item) => <li key={item.id} className="flex flex-wrap justify-between gap-3 py-3 text-sm"><span>{item.email}</span><span>{item.status} · expire le {new Date(item.expires_at).toLocaleDateString("fr-FR")}</span></li>)}</ul> : <p className="mt-3 text-slate-600">Aucune invitation.</p>}
      </section>
      <CompanyActions
        companyId={company.id}
        suspended={company.status === "suspended"}
        company={company}
        pendingInvitation={
          invitations.find((invitation) => invitation.status === "pending") ?? null
        }
      />
    </>
  );
}
