import { AdminLoginForm } from "./login-form";

export default function AdminLoginPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-100 px-4">
      <section className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-bold uppercase tracking-widest text-teal-700">Automa Platform</p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-950">
          Super-administration
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Accès strictement réservé aux administrateurs de la plateforme.
        </p>
        <AdminLoginForm />
      </section>
    </main>
  );
}
