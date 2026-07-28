import Link from "next/link";

import { requirePlatformAdmin } from "@/lib/platform";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const admin = await requirePlatformAdmin();
  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <a
        href="#admin-content"
        className="fixed left-4 top-3 z-50 -translate-y-20 bg-slate-950 px-4 py-2 text-white focus:translate-y-0"
      >
        Aller au contenu
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-4">
          <nav aria-label="Administration plateforme" className="flex items-center gap-6">
            <Link href="/admin" className="font-bold">
              Automa Platform
            </Link>
            <Link href="/admin/companies" className="text-sm font-semibold text-slate-700">
              Entreprises
            </Link>
          </nav>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-600 sm:inline">{admin.user.email}</span>
            <form action="/api/admin/auth/logout" method="post">
              <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">
                Déconnexion
              </button>
            </form>
          </div>
        </div>
      </header>
      <main id="admin-content" className="mx-auto max-w-7xl px-5 py-8" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
