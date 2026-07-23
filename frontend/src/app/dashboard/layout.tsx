import type { Metadata } from "next";
import Link from "next/link";

import { DashboardNavigation } from "@/app/dashboard/dashboard-navigation";
import { requireAuthContext } from "@/lib/auth";


export const metadata: Metadata = {
  title: "Dashboard exécutif",
  description: "Pilotage de l’activité, des risques et de la consommation.",
};

function Brand() {
  return (
    <Link
      href="/dashboard"
      className="flex w-fit items-center gap-3 rounded-lg text-slate-950 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-teal-700"
      aria-label="Automa — Dashboard"
    >
      <span className="brand-mark brand-mark-dark" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="text-lg font-bold tracking-[-0.03em]">Automa</span>
    </Link>
  );
}

export default async function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const auth = await requireAuthContext();

  return (
    <div className="min-h-screen bg-[#f4f7f7] text-slate-900">
      <a
        href="#dashboard-content"
        className="fixed left-4 top-3 z-50 -translate-y-20 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition focus:translate-y-0"
      >
        Aller au contenu principal
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-72 flex-col border-r border-slate-200 bg-white/95 px-6 py-7 backdrop-blur lg:flex">
        <Brand />

        <div className="mt-12">
          <p className="nav-caption">Pilotage</p>
          <DashboardNavigation />
        </div>

        <div className="mt-auto rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
              Environnement
            </p>
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
              Actif
            </span>
          </div>
          <p className="mt-3 text-sm font-semibold text-slate-800">{auth.company.name}</p>
          <p className="mt-1 truncate text-xs text-slate-500">
            {auth.role?.name ?? "Accès sans rôle"}
          </p>
          <p className="mt-1 truncate font-mono text-[11px] text-slate-400" title={auth.company.id}>
            {auth.company.id}
          </p>
        </div>
      </aside>

      <div className="min-h-screen lg:pl-72">
        <header className="sticky top-0 z-20 border-b border-slate-200/90 bg-[#f4f7f7]/90 backdrop-blur-xl">
          <div className="flex min-h-20 items-center justify-between gap-4 px-4 sm:px-6 lg:px-10 xl:px-14">
            <div className="lg:hidden">
              <Brand />
            </div>

            <div className="hidden min-w-0 lg:block">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">
                Espace de pilotage
              </p>
              <p className="mt-1 truncate text-sm text-slate-500">
                Données de démonstration · mise à jour il y a 2 min
              </p>
            </div>

            <div className="flex items-center gap-2 sm:gap-3">
              <span className="status-pill hidden sm:inline-flex">
                <span aria-hidden="true" /> Session sécurisée
              </span>
              <form action="/api/auth/logout" method="post">
                <button className="secondary-button whitespace-nowrap" type="submit">
                  Se déconnecter
                </button>
              </form>
            </div>
          </div>

          <details className="border-t border-slate-200 bg-white px-4 lg:hidden">
            <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between rounded-md text-sm font-semibold text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700">
              Navigation
              <span aria-hidden="true">＋</span>
            </summary>
            <DashboardNavigation mobile />
          </details>
        </header>

        <main
          id="dashboard-content"
          tabIndex={-1}
          className="px-4 py-7 outline-none sm:px-6 sm:py-9 lg:px-10 xl:px-14 xl:py-11"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
