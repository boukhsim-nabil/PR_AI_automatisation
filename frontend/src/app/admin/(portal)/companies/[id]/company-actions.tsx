"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function CompanyActions({
  companyId,
  suspended,
  company,
  pendingInvitation,
}: {
  companyId: string;
  suspended: boolean;
  company: {
    name: string;
    legal_name: string | null;
    sector: string | null;
    plan_code: string;
  };
  pendingInvitation: { id: string; email: string } | null;
}) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function suspend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = String(new FormData(event.currentTarget).get("reason") ?? "");
    if (!window.confirm("Confirmer la suspension de cette entreprise et la révocation de ses sessions ?")) return;
    await act("suspend", { reason });
  }

  async function updateCompany(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    await request(`/api/admin/platform/companies/${companyId}`, "PATCH", data);
  }

  async function inviteOwner(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ownerEmail = String(new FormData(event.currentTarget).get("owner_email") ?? "");
    await request(`/api/admin/platform/companies/${companyId}/invite-owner`, "POST", {
      owner_email: ownerEmail,
    });
  }

  async function revokeInvitation() {
    if (!pendingInvitation || !window.confirm("Révoquer cette invitation Owner ?")) return;
    await request(
      `/api/admin/platform/invitations/${pendingInvitation.id}/revoke`,
      "POST",
    );
  }

  async function request(path: string, method: "POST" | "PATCH", body?: object) {
    setPending(true);
    setError("");
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    if (!response?.ok) {
      const payload = await response?.json().catch(() => null);
      setError(payload?.detail ?? "L’action n’a pas pu être exécutée.");
      setPending(false);
      return false;
    }
    router.refresh();
    setPending(false);
    return true;
  }

  async function act(action: string, body?: object) {
    await request(`/api/admin/platform/companies/${companyId}/${action}`, "POST", body);
  }

  return (
    <>
      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
        <h2 className="text-xl font-bold">Informations modifiables</h2>
        <form onSubmit={updateCompany} className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-semibold">Nom commercial<input name="name" required defaultValue={company.name} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label>
          <label className="text-sm font-semibold">Raison sociale<input name="legal_name" defaultValue={company.legal_name ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label>
          <label className="text-sm font-semibold">Secteur<input name="sector" defaultValue={company.sector ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label>
          <label className="text-sm font-semibold">Plan<input name="plan_code" required defaultValue={company.plan_code} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label>
          <button disabled={pending} className="w-fit rounded-xl bg-slate-950 px-4 py-3 font-bold text-white">Enregistrer</button>
        </form>
      </section>
      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
        <h2 className="text-xl font-bold">Invitation Owner</h2>
        <form onSubmit={inviteOwner} className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label className="flex-1 text-sm font-semibold">Email Owner
            <input name="owner_email" type="email" required defaultValue={pendingInvitation?.email ?? ""} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" />
          </label>
          <button disabled={pending} className="self-end rounded-xl border border-slate-300 px-4 py-3 font-bold">
            {pendingInvitation ? "Renvoyer l’invitation" : "Inviter un Owner"}
          </button>
        </form>
        {pendingInvitation ? <button type="button" disabled={pending} onClick={revokeInvitation} className="mt-3 text-sm font-semibold text-red-700 underline">Révoquer l’invitation en attente</button> : null}
      </section>
      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
      <h2 className="text-xl font-bold">Actions sensibles</h2>
      {error ? <p role="alert" className="mt-3 text-sm text-red-700">{error}</p> : null}
      {suspended ? (
        <button disabled={pending} onClick={() => act("reactivate")} className="mt-4 rounded-xl bg-emerald-700 px-4 py-3 font-bold text-white">
          Réactiver l’entreprise
        </button>
      ) : (
        <form onSubmit={suspend} className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label className="flex-1 text-sm font-semibold">Motif obligatoire
            <input name="reason" minLength={5} required className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" />
          </label>
          <button disabled={pending} className="self-end rounded-xl bg-red-700 px-4 py-3 font-bold text-white">Suspendre</button>
        </form>
      )}
      </section>
    </>
  );
}
