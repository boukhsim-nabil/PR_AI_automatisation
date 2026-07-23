import type { Metadata } from "next";

import { LoginForm } from "./login-form";


export const metadata: Metadata = {
  title: "Connexion",
  description: "Accédez à votre espace d’automatisation sécurisé.",
};

export default function LoginPage() {
  return (
    <main className="login-page">
      <section className="login-story" aria-labelledby="story-title">
        <div className="story-orb story-orb-one" />
        <div className="story-orb story-orb-two" />

        <div className="relative z-10 flex h-full flex-col justify-between">
          <div className="brand-lockup">
            <span className="brand-mark" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span>Automa</span>
          </div>

          <div className="max-w-xl py-16">
            <p className="eyebrow-light">Espace de pilotage intelligent</p>
            <h1 id="story-title" className="mt-5 text-4xl font-semibold leading-tight tracking-[-0.04em] text-white sm:text-5xl lg:text-6xl">
              Vos opérations,
              <br />
              <span className="text-teal-200">enfin orchestrées.</span>
            </h1>
            <p className="mt-6 max-w-lg text-base leading-8 text-slate-300 sm:text-lg">
              Supervisez vos agents, vos workflows et vos décisions depuis un espace unique, traçable et sécurisé.
            </p>

            <div className="mt-10 grid gap-3 sm:grid-cols-3">
              {[
                ["01", "Décider"],
                ["02", "Automatiser"],
                ["03", "Mesurer"],
              ].map(([number, label]) => (
                <div className="story-step" key={number}>
                  <span>{number}</span>
                  <strong>{label}</strong>
                </div>
              ))}
            </div>
          </div>

          <p className="relative z-10 text-xs font-medium tracking-wide text-slate-400">
            Chiffrement en transit · Isolation par entreprise · Journal d’audit
          </p>
        </div>
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="w-full max-w-md">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <span className="brand-mark brand-mark-dark" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span className="text-lg font-bold tracking-tight text-slate-950">Automa</span>
          </div>

          <p className="eyebrow">Portail entreprise</p>
          <h2 id="login-title" className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-slate-950 sm:text-4xl">
            Heureux de vous revoir.
          </h2>
          <p className="mt-3 text-base leading-7 text-slate-500">
            Connectez-vous pour retrouver votre environnement de travail.
          </p>

          <LoginForm />

          <div className="mt-8 flex items-start gap-3 border-t border-slate-200 pt-6 text-sm leading-6 text-slate-500">
            <span className="security-dot" aria-hidden="true" />
            <p>
              Connexion protégée. Une vérification MFA peut être demandée selon la politique de votre entreprise.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
