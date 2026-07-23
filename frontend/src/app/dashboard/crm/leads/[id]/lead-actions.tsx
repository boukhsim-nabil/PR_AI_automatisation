"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { Assignee, CrmTask, LeadStatus, statusLabels } from "@/lib/crm";

type Capabilities = {
  update: boolean;
  assign: boolean;
  addActivity: boolean;
  manageTasks: boolean;
};

async function api(path: string, body?: object): Promise<Response> {
  return fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function LeadActions({
  leadId,
  currentStatus,
  currentAssignee,
  contactId,
  assignees,
  tasks,
  capabilities,
}: {
  leadId: string;
  currentStatus: LeadStatus;
  currentAssignee: string | null;
  contactId: string;
  assignees: Assignee[];
  tasks: CrmTask[];
  capabilities: Capabilities;
}) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [status, setStatus] = useState<LeadStatus>(currentStatus);

  async function run(key: string, request: () => Promise<Response>, success: string) {
    if (pending) return;
    setPending(key);
    setNotice(null);
    try {
      const response = await request();
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: string };
        setNotice(payload.detail ?? "L’action a échoué.");
        return;
      }
      setNotice(success);
      router.refresh();
    } catch {
      setNotice("Le service CRM est indisponible.");
    } finally {
      setPending(null);
    }
  }

  function changeStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void run(
      "status",
      () =>
        api(`/api/crm/leads/${leadId}/status`, {
          status,
          lost_reason: status === "lost" ? data.get("lost_reason") : null,
        }),
      "Statut mis à jour.",
    );
  }

  function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void run(
      "assign",
      () =>
        api(`/api/crm/leads/${leadId}/assign`, {
          assigned_membership_id: data.get("assigned_membership_id") || null,
        }),
      "Responsable mis à jour.",
    );
  }

  function addNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void run(
      "note",
      () =>
        api(`/api/crm/leads/${leadId}/activities`, {
          activity_type: "note",
          subject: data.get("subject"),
          description: data.get("description") || null,
        }),
      "Note ajoutée.",
    ).then(() => form.reset());
  }

  function addTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const dueAt = String(data.get("due_at") || "");
    void run(
      "task",
      () =>
        api("/api/crm/tasks", {
          lead_id: leadId,
          contact_id: contactId,
          title: data.get("title"),
          priority: data.get("priority"),
          assigned_membership_id: data.get("assigned_membership_id") || null,
          due_at: dueAt ? new Date(dueAt).toISOString() : null,
        }),
      "Tâche créée.",
    ).then(() => form.reset());
  }

  return (
    <div className="space-y-6">
      <div aria-live="polite" className="min-h-6 text-sm font-semibold text-teal-800">{notice}</div>

      {capabilities.update ? (
        <form onSubmit={changeStatus} className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="font-bold text-slate-950">Changer le statut</h2>
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              Statut
              <select className="crm-input" value={status} onChange={(event) => setStatus(event.target.value as LeadStatus)}>
                {(Object.entries(statusLabels) as Array<[LeadStatus, string]>)
                  .filter(([key]) => key !== "archived")
                  .map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            {status === "lost" ? (
              <label className="grid gap-1.5 text-sm font-medium text-slate-700">
                Motif de perte
                <textarea className="crm-input min-h-20" name="lost_reason" required maxLength={1000} />
              </label>
            ) : null}
            <button className="secondary-button justify-center" disabled={pending !== null} type="submit">
              {pending === "status" ? "Mise à jour…" : "Mettre à jour"}
            </button>
          </div>
        </form>
      ) : null}

      {capabilities.assign ? (
        <form onSubmit={assign} className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="font-bold text-slate-950">Attribution</h2>
          <label className="mt-4 grid gap-1.5 text-sm font-medium text-slate-700">
            Responsable
            <select className="crm-input" name="assigned_membership_id" defaultValue={currentAssignee ?? ""}>
              <option value="">Non attribué</option>
              {assignees.map((assignee) => (
                <option key={assignee.membership_id} value={assignee.membership_id}>
                  {assignee.display_name ?? assignee.email}
                </option>
              ))}
            </select>
          </label>
          <button className="secondary-button mt-3 w-full justify-center" disabled={pending !== null} type="submit">Attribuer</button>
        </form>
      ) : null}

      {capabilities.addActivity ? (
        <form onSubmit={addNote} className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="font-bold text-slate-950">Ajouter une note</h2>
          <label className="mt-4 grid gap-1.5 text-sm font-medium text-slate-700">
            Sujet
            <input className="crm-input" name="subject" required maxLength={255} />
          </label>
          <label className="mt-3 grid gap-1.5 text-sm font-medium text-slate-700">
            Note
            <textarea className="crm-input min-h-24" name="description" maxLength={4000} />
          </label>
          <button className="secondary-button mt-3 w-full justify-center" disabled={pending !== null} type="submit">Ajouter la note</button>
        </form>
      ) : null}

      {capabilities.manageTasks ? (
        <form onSubmit={addTask} className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="font-bold text-slate-950">Nouvelle tâche</h2>
          <label className="mt-4 grid gap-1.5 text-sm font-medium text-slate-700">
            Titre
            <input className="crm-input" name="title" required maxLength={255} />
          </label>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              Priorité
              <select className="crm-input" name="priority" defaultValue="medium">
                <option value="low">Faible</option><option value="medium">Moyenne</option>
                <option value="high">Haute</option><option value="urgent">Urgente</option>
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-slate-700">
              Échéance
              <input className="crm-input" name="due_at" type="datetime-local" />
            </label>
          </div>
          <label className="mt-3 grid gap-1.5 text-sm font-medium text-slate-700">
            Responsable
            <select className="crm-input" name="assigned_membership_id" defaultValue="">
              <option value="">Non attribué</option>
              {assignees.map((assignee) => (
                <option key={assignee.membership_id} value={assignee.membership_id}>{assignee.display_name ?? assignee.email}</option>
              ))}
            </select>
          </label>
          <button className="secondary-button mt-3 w-full justify-center" disabled={pending !== null} type="submit">Créer la tâche</button>
        </form>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-labelledby="tasks-title">
        <h2 id="tasks-title" className="font-bold text-slate-950">Tâches</h2>
        {tasks.length === 0 ? <p className="mt-3 text-sm text-slate-500">Aucune tâche.</p> : (
          <ul className="mt-3 divide-y divide-slate-100">
            {tasks.map((task) => (
              <li key={task.id} className="flex items-center justify-between gap-3 py-3">
                <div><p className="text-sm font-semibold text-slate-800">{task.title}</p><p className="text-xs text-slate-500">{task.status}</p></div>
                {capabilities.manageTasks && task.status !== "completed" ? (
                  <button className="secondary-button px-3 py-2" disabled={pending !== null} type="button" onClick={() => void run(`complete-${task.id}`, () => api(`/api/crm/tasks/${task.id}/complete`), "Tâche terminée.")}>Terminer</button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
