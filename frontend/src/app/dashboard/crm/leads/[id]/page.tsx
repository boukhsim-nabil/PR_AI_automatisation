import Link from "next/link";
import { notFound } from "next/navigation";

import { LeadActions } from "@/app/dashboard/crm/leads/[id]/lead-actions";
import { ApiError } from "@/lib/api-error";
import { requireAuthContext } from "@/lib/auth";
import { crmGet } from "@/lib/crm-server";
import {
  Assignee,
  CrmActivity,
  CrmTask,
  Lead,
  PageResult,
  priorityLabels,
  statusLabels,
} from "@/lib/crm";

export const dynamic = "force-dynamic";

export default async function LeadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const auth = await requireAuthContext();
  if (!auth.permissions.includes("crm.read")) notFound();
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();

  let lead: Lead;
  let activities: PageResult<CrmActivity>;
  let tasks: PageResult<CrmTask>;
  let assignees: Assignee[];
  try {
    [lead, activities, tasks, assignees] = await Promise.all([
      crmGet<Lead>(`leads/${id}`),
      crmGet<PageResult<CrmActivity>>(`leads/${id}/activities?page_size=100`),
      crmGet<PageResult<CrmTask>>(`tasks?lead_id=${id}&page_size=100`),
      auth.permissions.includes("members.read")
        ? crmGet<Assignee[]>("assignees")
        : Promise.resolve([]),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.kind === "not_found") notFound();
    throw error;
  }
  const assignee = assignees.find((item) => item.membership_id === lead.assigned_membership_id);

  return (
    <div className="space-y-7">
      <header>
        <Link className="text-sm font-semibold text-teal-700 hover:underline" href="/dashboard/crm">← Retour au CRM</Link>
        <div className="mt-4 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Fiche prospect</p>
            <h1 className="mt-2 text-3xl font-bold text-slate-950">{[lead.contact.first_name, lead.contact.last_name].filter(Boolean).join(" ")}</h1>
            <p className="mt-1 text-slate-600">{lead.title}</p>
          </div>
          <div className="flex flex-wrap gap-2 text-sm">
            <span className="rounded-full bg-sky-50 px-3 py-1.5 font-semibold text-sky-700 ring-1 ring-sky-200">{statusLabels[lead.status]}</span>
            <span className="rounded-full bg-violet-50 px-3 py-1.5 font-semibold text-violet-700 ring-1 ring-violet-200">Priorité {priorityLabels[lead.priority].toLowerCase()}</span>
            <span className="rounded-full bg-slate-100 px-3 py-1.5 font-semibold text-slate-700 ring-1 ring-slate-200">Score {lead.score}/100</span>
          </div>
        </div>
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm" aria-labelledby="contact-title">
            <h2 id="contact-title" className="text-lg font-bold text-slate-950">Contact</h2>
            <dl className="mt-5 grid gap-4 sm:grid-cols-2">
              {[["Email", lead.contact.email], ["Téléphone", lead.contact.phone], ["Organisation", lead.contact.organization_name], ["Fonction", lead.contact.job_title], ["Langue", lead.contact.language], ["Responsable", assignee?.display_name ?? assignee?.role ?? "Non attribué"]].map(([label, value]) => (
                <div key={label}><dt className="text-xs font-semibold uppercase tracking-wider text-slate-600">{label}</dt><dd className="mt-1 break-words text-sm font-medium text-slate-800">{value ?? "Non renseigné"}</dd></div>
              ))}
            </dl>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm" aria-labelledby="opportunity-title">
            <h2 id="opportunity-title" className="text-lg font-bold text-slate-950">Opportunité</h2>
            <dl className="mt-5 grid gap-4 sm:grid-cols-2">
              {[["Besoin", lead.need_description], ["Budget", lead.estimated_budget ? `${lead.estimated_budget} ${lead.currency}` : null], ["Urgence", lead.urgency], ["Source", lead.source], ["Prochaine action", lead.next_action], ["Date", lead.next_action_at ? new Date(lead.next_action_at).toLocaleString("fr-FR") : null], ["Motif de perte", lead.lost_reason]].map(([label, value]) => (
                <div key={label}><dt className="text-xs font-semibold uppercase tracking-wider text-slate-600">{label}</dt><dd className="mt-1 break-words text-sm font-medium text-slate-800">{value ?? "Non renseigné"}</dd></div>
              ))}
            </dl>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm" aria-labelledby="timeline-title">
            <h2 id="timeline-title" className="text-lg font-bold text-slate-950">Chronologie</h2>
            {!activities?.items.length ? <p className="mt-4 text-sm text-slate-600">Aucune activité.</p> : (
              <ol className="mt-5 space-y-4 border-l-2 border-slate-100 pl-5">
                {activities.items.map((activity) => (
                  <li key={activity.id} className="relative">
                    <span className="absolute -left-[1.7rem] top-1.5 h-3 w-3 rounded-full bg-teal-500 ring-4 ring-white" aria-hidden="true" />
                    <div className="flex flex-wrap items-baseline justify-between gap-2"><p className="font-semibold text-slate-900">{activity.subject}</p><time dateTime={activity.occurred_at} className="text-xs text-slate-600">{new Date(activity.occurred_at).toLocaleString("fr-FR")}</time></div>
                    <p className="mt-1 text-xs font-semibold uppercase tracking-wider text-teal-700">{activity.activity_type}</p>
                    {activity.description ? <p className="mt-2 text-sm text-slate-600">{activity.description}</p> : null}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>

        <LeadActions
          leadId={lead.id}
          contactId={lead.contact.id}
          currentStatus={lead.status}
          currentAssignee={lead.assigned_membership_id}
          assignees={assignees}
          tasks={tasks.items}
          capabilities={{
            update: auth.permissions.includes("crm.update"),
            assign: auth.permissions.includes("crm.assign"),
            addActivity: auth.permissions.includes("crm.activities.create"),
            manageTasks: auth.permissions.includes("crm.tasks.manage"),
          }}
        />
      </div>
    </div>
  );
}
