import Link from "next/link";

import { PlatformCompany, platformBackendFetch } from "@/lib/platform";

type Page = { items: PlatformCompany[]; total: number; page: number; pages: number };

export default async function CompaniesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["search", "status", "plan", "country", "page"]) {
    const value = params[key];
    if (typeof value === "string" && value) query.set(key, value);
  }
  const response = await platformBackendFetch(`/v1/platform/companies?${query}`);
  if (!response.ok) throw new Error("Impossible de charger les entreprises.");
  const data = (await response.json()) as Page;
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Entreprises clientes</h1>
          <p className="mt-2 text-sm text-slate-600">{data.total} entreprise(s)</p>
        </div>
        <Link href="/admin/companies/new" className="rounded-xl bg-slate-950 px-4 py-3 text-sm font-bold text-white">
          Créer un client
        </Link>
      </div>
      <form className="mt-7 grid gap-3 rounded-2xl bg-white p-4 sm:grid-cols-4">
        <label className="sm:col-span-2">
          <span className="sr-only">Rechercher</span>
          <input name="search" defaultValue={typeof params.search === "string" ? params.search : ""} placeholder="Nom, raison sociale ou slug" className="w-full rounded-lg border border-slate-300 px-3 py-2" />
        </label>
        <select name="status" defaultValue={typeof params.status === "string" ? params.status : ""} aria-label="Statut" className="rounded-lg border border-slate-300 px-3 py-2">
          <option value="">Tous les statuts</option>
          {["pending", "onboarding", "active", "suspended", "closed"].map((value) => <option key={value}>{value}</option>)}
        </select>
        <button className="rounded-lg border border-slate-300 px-3 py-2 font-semibold">Filtrer</button>
      </form>
      {data.items.length === 0 ? (
        <p className="mt-8 rounded-2xl border border-dashed border-slate-300 p-8 text-center text-slate-600">Aucune entreprise ne correspond aux filtres.</p>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-slate-50 text-slate-600"><tr>{["Nom", "Statut", "Plan", "Pays", "Owner", "Onboarding", "Créée le"].map((h) => <th key={h} className="px-4 py-3 font-semibold">{h}</th>)}</tr></thead>
            <tbody>
              {data.items.map((company) => (
                <tr key={company.id} className="border-t border-slate-100">
                  <td className="px-4 py-4"><Link className="font-semibold text-teal-800 underline-offset-4 hover:underline" href={`/admin/companies/${company.id}`}>{company.name}</Link></td>
                  <td className="px-4 py-4">{company.status}</td><td className="px-4 py-4">{company.plan_code}</td>
                  <td className="px-4 py-4">{company.country}</td><td className="px-4 py-4">{company.owner_email ?? "—"}</td>
                  <td className="px-4 py-4">{company.onboarding_status}</td><td className="px-4 py-4">{new Date(company.created_at).toLocaleDateString("fr-FR")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
