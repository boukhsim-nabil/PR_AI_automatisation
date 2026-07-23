"use client";

import { useEffect } from "react";


export function RefreshClient({ returnTo }: { returnTo: string }) {
  useEffect(() => {
    let active = true;
    void fetch("/api/auth/refresh", { method: "POST" })
      .then((response) => {
        if (!active) return;
        window.location.replace(response.ok ? returnTo : "/login");
      })
      .catch(() => {
        if (active) window.location.replace("/login");
      });
    return () => {
      active = false;
    };
  }, [returnTo]);

  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-6">
      <p className="text-sm font-semibold text-slate-600" role="status">
        Renouvellement sécurisé de la session…
      </p>
    </main>
  );
}
