"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function CompanyActions({
  companyId,
  suspended,
}: {
  companyId: string;
  suspended: boolean;
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

  async function act(action: string, body?: object) {
    setPending(true);
    setError("");
    const response = await fetch(`/api/admin/platform/companies/${companyId}/${action}`, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    if (!response?.ok) {
      setError("L’action n’a pas pu être exécutée.");
      setPending(false);
      return;
    }
    router.refresh();
    setPending(false);
  }

  return (
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
  );
}
