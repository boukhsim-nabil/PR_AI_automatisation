"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { CRM_ACTIVITY_CREATED_EVENT } from "@/app/dashboard/crm/leads/[id]/activity-timeline";
import { Assignee, CrmActivity, CrmTask, LeadStatus, statusLabels } from "@/lib/crm";
import { apiErrorFromResponse, userFacingApiError } from "@/lib/api-error";

type Capabilities = {
  update: boolean;
  assign: boolean;
  addActivity: boolean;
  manageTasks: boolean;
};
type Notice = { kind: "success" | "error"; message: string };

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
  const [notice, setNotice] = useState<Notice | null>(null);
  const [status, setStatus] = useState<LeadStatus>(currentStatus);
  const [taskItems, setTaskItems] = useState<CrmTask[]>(tasks);

  async function run(
    key: string,
    request: () => Promise<Response>,
    success: string,
    onSuccess?: (response: Response) => Promise<void> | void,
  ): Promise<boolean> {
    if (pending) return false;
    setPending(key);
    setNotice(null);
    try {
      const response = await request();
      if (!response.ok) {
        setNotice({ kind: "error", message: userFacingApiError(await apiErrorFromResponse(response)) });
        return false;
      }
      await onSuccess?.(response);
      setNotice({ kind: "success", message: success });
      router.refresh();
      return true;
    } catch {
      setNotice({ kind: "error", message: "Le service CRM est indisponible." });
      return false;
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

  async function addNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const succeeded = await run(
      "note",
      () =>
        api(`/api/crm/leads/${leadId}/activities`, {
          activity_type: "note",
          subject: data.get("subject"),
          description: data.get("description") || null,
        }),
      "Note ajoutée.",
      async (response) => {
        const activity = (await response.json()) as CrmActivity;
        window.dispatchEvent(
          new CustomEvent<CrmActivity>(CRM_ACTIVITY_CREATED_EVENT, { detail: activity }),
        );
      },
    );
    if (succeeded) form.reset();
  }

  async function addTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const dueAt = String(data.get("due_at") || "");
    const succeeded = await run(
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
      async (response) => {
        const created = (await response.json()) as CrmTask;
        setTaskItems((current) => [created, ...current]);
      },
    );
    if (succeeded) form.reset();
  }

  return (
    <div className="space-y-6">
      <div
        role={notice?.kind === "error" ? "alert" : "status"}
        aria-live={notice?.kind === "error" ? "assertive" : "polite"}
        className={`min-h-6 text-sm font-semibold ${
          notice?.kind === "error" ? "text-rose-700" : "text-teal-800"
        }`}
      >
        {notice?.message}
      </div>

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
                  {assignee.display_name ?? assignee.role ?? "Membre actif"}
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
                <option key={assignee.membership_id} value={assignee.membership_id}>{assignee.display_name ?? assignee.role ?? "Membre actif"}</option>
              ))}
            </select>
          </label>
          <button className="secondary-button mt-3 w-full justify-center" disabled={pending !== null} type="submit">Créer la tâche</button>
        </form>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-labelledby="tasks-title">
        <h2 id="tasks-title" className="font-bold text-slate-950">Tâches</h2>
        {taskItems.length === 0 ? <p className="mt-3 text-sm text-slate-600">Aucune tâche.</p> : (
          <ul className="mt-3 divide-y divide-slate-100">
            {taskItems.map((task) => (
              <li key={task.id} className="flex items-center justify-between gap-3 py-3">
                <div><p className="text-sm font-semibold text-slate-800">{task.title}</p><p className="text-xs text-slate-600">{task.status}</p></div>
                {capabilities.manageTasks && task.status !== "completed" ? (
                  <button className="secondary-button px-3 py-2" disabled={pending !== null} type="button" onClick={() => void run(`complete-${task.id}`, () => api(`/api/crm/tasks/${task.id}/complete`), "Tâche terminée.", async (response) => {
                    const completed = (await response.json()) as CrmTask;
                    setTaskItems((current) => current.map((item) => item.id === completed.id ? completed : item));
                  })}>Terminer</button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
