import { AcceptInvitationForm } from "./accept-form";

export default async function AcceptInvitationPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token = "" } = await searchParams;
  return (
    <main className="grid min-h-screen place-items-center bg-slate-100 px-4 py-10">
      <section className="w-full max-w-xl rounded-3xl bg-white p-8 shadow-sm">
        <h1 className="text-3xl font-bold">Rejoindre votre entreprise</h1>
        <p className="mt-2 text-slate-600">Définissez vos accès de façon sécurisée.</p>
        <AcceptInvitationForm token={token} />
      </section>
    </main>
  );
}
