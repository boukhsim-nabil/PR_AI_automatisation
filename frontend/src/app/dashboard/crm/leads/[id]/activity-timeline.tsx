"use client";

import { useEffect, useState } from "react";

import { CrmActivity } from "@/lib/crm";

export const CRM_ACTIVITY_CREATED_EVENT = "crm:activity-created";

export function ActivityTimeline({ activities }: { activities: CrmActivity[] }) {
  const [items, setItems] = useState(activities);

  useEffect(() => {
    function addActivity(event: Event) {
      const activity = (event as CustomEvent<CrmActivity>).detail;
      setItems((current) =>
        current.some((item) => item.id === activity.id) ? current : [activity, ...current],
      );
    }
    window.addEventListener(CRM_ACTIVITY_CREATED_EVENT, addActivity);
    return () => window.removeEventListener(CRM_ACTIVITY_CREATED_EVENT, addActivity);
  }, []);

  return (
    <section
      className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"
      aria-labelledby="timeline-title"
    >
      <h2 id="timeline-title" className="text-lg font-bold text-slate-950">
        Chronologie
      </h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-slate-600">Aucune activité.</p>
      ) : (
        <ol className="mt-5 space-y-4 border-l-2 border-slate-100 pl-5">
          {items.map((activity) => (
            <li key={activity.id} className="relative">
              <span
                className="absolute -left-[1.7rem] top-1.5 h-3 w-3 rounded-full bg-teal-500 ring-4 ring-white"
                aria-hidden="true"
              />
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-semibold text-slate-900">{activity.subject}</p>
                <time dateTime={activity.occurred_at} className="text-xs text-slate-600">
                  {new Date(activity.occurred_at).toLocaleString("fr-FR")}
                </time>
              </div>
              <p className="mt-1 text-xs font-semibold uppercase tracking-wider text-teal-700">
                {activity.activity_type}
              </p>
              {activity.description ? (
                <p className="mt-2 text-sm text-slate-600">{activity.description}</p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
