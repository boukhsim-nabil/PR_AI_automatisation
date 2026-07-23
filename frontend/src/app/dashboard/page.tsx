type Metric = {
  label: string;
  value: string;
  detail: string;
};

type KpiGroup = {
  id: string;
  eyebrow: string;
  title: string;
  summary: string;
  tone: "teal" | "amber" | "blue" | "violet";
  metrics: Metric[];
};

const kpiGroups: KpiGroup[] = [
  {
    id: "activity",
    eyebrow: "Activité du jour",
    title: "1 248 interactions",
    summary: "+18 % par rapport à hier",
    tone: "teal",
    metrics: [
      { label: "Messages", value: "1 248", detail: "tous canaux" },
      { label: "Prospects", value: "36", detail: "nouveaux" },
      { label: "Rendez-vous", value: "12", detail: "confirmés" },
    ],
  },
  {
    id: "attention",
    eyebrow: "À traiter",
    title: "9 actions requises",
    summary: "2 éléments critiques",
    tone: "amber",
    metrics: [
      { label: "Validations", value: "7", detail: "en attente" },
      { label: "Erreurs", value: "2", detail: "à investiguer" },
      { label: "Sans suivi", value: "4", detail: "prospects" },
    ],
  },
  {
    id: "performance",
    eyebrow: "Performance & automatisation",
    title: "98,7 % de succès",
    summary: "31 h économisées cette semaine",
    tone: "blue",
    metrics: [
      { label: "Temps de réponse", value: "48 s", detail: "médiane" },
      { label: "Exécutions", value: "1 426", detail: "aujourd’hui" },
      { label: "Réussies", value: "98,7 %", detail: "+1,2 pt" },
    ],
  },
  {
    id: "usage",
    eyebrow: "Consommation",
    title: "68 % du quota",
    summary: "Prévision dans la limite du forfait",
    tone: "violet",
    metrics: [
      { label: "Tokens IA", value: "2,4 M", detail: "ce mois" },
      { label: "Messages", value: "8 420", detail: "sur 12 000" },
      { label: "Quota restant", value: "32 %", detail: "12 jours" },
    ],
  },
];

const tones = {
  teal: {
    bar: "bg-teal-500",
    badge: "bg-teal-50 text-teal-700 ring-teal-200",
    wash: "from-teal-50/80",
  },
  amber: {
    bar: "bg-amber-500",
    badge: "bg-amber-50 text-amber-800 ring-amber-200",
    wash: "from-amber-50/80",
  },
  blue: {
    bar: "bg-sky-500",
    badge: "bg-sky-50 text-sky-700 ring-sky-200",
    wash: "from-sky-50/80",
  },
  violet: {
    bar: "bg-violet-500",
    badge: "bg-violet-50 text-violet-700 ring-violet-200",
    wash: "from-violet-50/80",
  },
} as const;

const weeklyExecutions = [
  { day: "Lun", value: 62 },
  { day: "Mar", value: 76 },
  { day: "Mer", value: 68 },
  { day: "Jeu", value: 91 },
  { day: "Ven", value: 84 },
  { day: "Sam", value: 53 },
  { day: "Dim", value: 72 },
];

function KpiCard({ group }: { group: KpiGroup }) {
  const tone = tones[group.tone];

  return (
    <article
      id={group.id}
      className={`scroll-mt-36 overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br ${tone.wash} via-white to-white shadow-[0_18px_50px_rgba(30,50,50,0.05)]`}
      aria-labelledby={`${group.id}-title`}
    >
      <div className={`h-1 ${tone.bar}`} />
      <div className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">
              {group.eyebrow}
            </p>
            <h2 id={`${group.id}-title`} className="mt-3 text-xl font-semibold tracking-[-0.025em] text-slate-950">
              {group.title}
            </h2>
          </div>
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ring-1 ring-inset ${tone.badge}`}>
            Mock
          </span>
        </div>
        <p className="mt-2 text-sm leading-6 text-slate-500">{group.summary}</p>

        <dl className="mt-6 grid grid-cols-3 gap-2 border-t border-slate-200/80 pt-5">
          {group.metrics.map((metric) => (
            <div className="min-w-0" key={metric.label}>
              <dt className="truncate text-xs text-slate-500" title={metric.label}>{metric.label}</dt>
              <dd className="mt-1 text-lg font-semibold tracking-tight text-slate-900 sm:text-xl">
                {metric.value}
              </dd>
              <p className="mt-0.5 truncate text-[11px] text-slate-400">{metric.detail}</p>
            </div>
          ))}
        </dl>
      </div>
    </article>
  );
}

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-[1600px]">
      <section id="overview" className="scroll-mt-36" aria-labelledby="dashboard-title">
        <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <p className="eyebrow">Vue d’ensemble</p>
            <h1 id="dashboard-title" className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-4xl xl:text-5xl">
              Dashboard exécutif
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500 sm:text-base">
              L’essentiel de l’activité, des interventions et de la valeur produite par vos automatisations.
            </p>
          </div>

          <div className="flex flex-wrap gap-2" aria-label="Filtres du dashboard">
            <button className="filter-button" type="button" aria-label="Période : aujourd’hui">
              Aujourd’hui
              <span className="ml-2 text-slate-400" aria-hidden="true">⌄</span>
            </button>
            <button className="filter-button" type="button" aria-label="Équipe : toutes les équipes">
              Toutes les équipes
              <span className="ml-2 text-slate-400" aria-hidden="true">⌄</span>
            </button>
          </div>
        </div>

        <div className="mt-7 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm leading-6 text-sky-900" role="status">
          <span className="font-semibold">Données de démonstration.</span>{" "}
          Les indicateurs seront remplacés par les flux métier dès la connexion des premières sources.
        </div>

        <section className="mt-5 grid gap-4 xl:grid-cols-2 2xl:grid-cols-4" aria-label="Indicateurs clés">
          {kpiGroups.map((group) => <KpiCard group={group} key={group.id} />)}
        </section>
      </section>

      <section className="mt-5 grid gap-4 xl:grid-cols-[1.55fr_1fr]" aria-label="Analyse opérationnelle">
        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_18px_50px_rgba(30,50,50,0.04)] sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="card-kicker">Évolution sur 7 jours</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">Exécutions automatisées</h2>
              <p className="mt-1 text-sm text-slate-500">9 842 exécutions · +12,4 % sur la période précédente</p>
            </div>
            <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700 ring-1 ring-inset ring-emerald-200">
              Tendance positive
            </span>
          </div>

          <div className="mt-8 grid h-52 grid-cols-7 items-end gap-2 sm:gap-4" aria-label="Exécutions par jour, données simulées">
            {weeklyExecutions.map((item) => (
              <div className="flex h-full flex-col justify-end gap-3" key={item.day}>
                <span className="sr-only">{item.day} : {item.value}% du maximum hebdomadaire</span>
                <div className="relative flex-1 overflow-hidden rounded-md bg-slate-100">
                  <div
                    className="absolute inset-x-0 bottom-0 rounded-md bg-gradient-to-t from-teal-700 to-teal-400"
                    style={{ height: `${item.value}%` }}
                    aria-hidden="true"
                  />
                </div>
                <span className="text-center text-xs font-medium text-slate-500">{item.day}</span>
              </div>
            ))}
          </div>
        </article>

        <article id="health" className="scroll-mt-36 rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_18px_50px_rgba(30,50,50,0.04)] sm:p-6" aria-labelledby="health-title">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="card-kicker">Santé opérationnelle</p>
              <h2 id="health-title" className="mt-2 text-xl font-semibold tracking-tight text-slate-950">Agents & intégrations</h2>
            </div>
            <span className="rounded-full bg-amber-50 px-3 py-1.5 text-xs font-bold text-amber-800 ring-1 ring-inset ring-amber-200">
              1 attention
            </span>
          </div>

          <ul className="mt-6 divide-y divide-slate-100">
            {[
              ["Agents IA", "6 sur 6 opérationnels", "Disponible"],
              ["Workflows", "24 actifs", "Disponible"],
              ["Connecteurs", "1 authentification expire bientôt", "Attention"],
              ["Incidents", "Aucun incident en cours", "Disponible"],
            ].map(([label, detail, status]) => (
              <li className="flex items-center justify-between gap-4 py-3.5" key={label}>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-800">{label}</p>
                  <p className="mt-1 truncate text-xs text-slate-500">{detail}</p>
                </div>
                <span className={`shrink-0 text-xs font-bold ${status === "Attention" ? "text-amber-700" : "text-emerald-700"}`}>
                  <span aria-hidden="true">{status === "Attention" ? "△" : "●"}</span>{" "}{status}
                </span>
              </li>
            ))}
          </ul>

          <button className="secondary-button mt-5 w-full" type="button">
            Ouvrir le centre d’incidents
          </button>
        </article>
      </section>
    </div>
  );
}
