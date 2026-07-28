import { CompanyForm } from "./company-form";

export default function NewCompanyPage() {
  return (
    <>
      <p className="text-sm font-bold uppercase tracking-wider text-teal-700">Provisioning</p>
      <h1 className="mt-2 text-3xl font-bold">Nouvelle entreprise cliente</h1>
      <p className="mt-2 max-w-2xl text-slate-600">Le futur Owner recevra une invitation à usage unique. Aucun utilisateur incomplet ni mot de passe temporaire ne sera créé.</p>
      <CompanyForm />
    </>
  );
}
