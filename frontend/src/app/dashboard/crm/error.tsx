"use client";

export default function CrmError({ reset }: { reset: () => void }) {
  return (
    <section className="rounded-3xl border border-rose-200 bg-rose-50 p-8" role="alert">
      <h1 className="text-2xl font-bold text-rose-950">Le CRM n’a pas pu être affiché</h1>
      <p className="mt-2 text-rose-800">Aucune donnée n’a été modifiée. Vous pouvez relancer le chargement.</p>
      <button className="secondary-button mt-5" type="button" onClick={reset}>Réessayer</button>
    </section>
  );
}
