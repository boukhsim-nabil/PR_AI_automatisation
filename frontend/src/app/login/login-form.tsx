"use client";

import { FormEvent, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";


const subscribeToHydration = () => () => {};


export function LoginForm() {
  const router = useRouter();
  const isHydrated = useSyncExternalStore(
    subscribeToHydration,
    () => true,
    () => false,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isLoading) return;

    setIsLoading(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
        }),
      });
      const result = (await response.json()) as { message?: string };

      if (!response.ok) {
        setError(
          result.message ??
            "Connexion impossible. Vérifiez vos informations ou contactez votre administrateur.",
        );
        return;
      }

      router.replace("/dashboard");
      router.refresh();
    } catch {
      setError(
        "Le service ne répond pas. Votre session n’a pas été ouverte ; vérifiez votre connexion puis réessayez.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <form
      className="mt-8 space-y-5"
      data-hydrated={isHydrated}
      onSubmit={handleSubmit}
    >
      <div className="space-y-2">
        <label className="form-label" htmlFor="email">
          Adresse email
        </label>
        <div className="field-shell">
          <svg aria-hidden="true" viewBox="0 0 24 24" className="field-icon">
            <path d="M3.5 6.75A2.25 2.25 0 0 1 5.75 4.5h12.5a2.25 2.25 0 0 1 2.25 2.25v10.5a2.25 2.25 0 0 1-2.25 2.25H5.75a2.25 2.25 0 0 1-2.25-2.25V6.75Z" />
            <path d="m4.25 6 6.25 5a2.4 2.4 0 0 0 3 0l6.25-5" />
          </svg>
          <input
            className="form-input"
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            inputMode="email"
            placeholder="vous@entreprise.com"
            required
            disabled={isLoading}
            aria-describedby={error ? "login-error" : undefined}
          />
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-4">
          <label className="form-label" htmlFor="password">
            Mot de passe
          </label>
          <a
            className="text-sm font-semibold text-teal-700 underline-offset-4 hover:underline focus-visible:rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
            href="mailto:support@automation.local?subject=Récupération%20du%20mot%20de%20passe"
          >
            Mot de passe oublié ?
          </a>
        </div>
        <div className="field-shell">
          <svg aria-hidden="true" viewBox="0 0 24 24" className="field-icon">
            <rect x="4" y="10" width="16" height="10" rx="2" />
            <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v2" />
          </svg>
          <input
            className="form-input pr-20"
            id="password"
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            placeholder="Votre mot de passe"
            required
            disabled={isLoading}
            aria-describedby={error ? "login-error" : undefined}
          />
          <button
            className="absolute inset-y-0 right-0 px-4 text-sm font-semibold text-slate-500 transition hover:text-slate-900 focus-visible:rounded-r-xl focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-teal-600"
            type="button"
            onClick={() => setShowPassword((visible) => !visible)}
            aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
            disabled={isLoading}
          >
            {showPassword ? "Masquer" : "Afficher"}
          </button>
        </div>
      </div>

      {error ? (
        <div
          id="login-error"
          className="flex gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-900"
          role="alert"
          aria-live="assertive"
        >
          <span
            aria-hidden="true"
            className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-rose-100 font-bold"
          >
            !
          </span>
          <p>{error}</p>
        </div>
      ) : null}

      <button
        className="primary-button"
        type="submit"
        disabled={isLoading || !isHydrated}
        aria-busy={isLoading}
      >
        {isLoading ? (
          <>
            <span className="button-spinner" aria-hidden="true" />
            Connexion sécurisée…
          </>
        ) : (
          <>
            Se connecter
            <span aria-hidden="true">→</span>
          </>
        )}
      </button>
    </form>
  );
}
