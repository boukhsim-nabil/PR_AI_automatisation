"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navigation = [
  { label: "Vue d’ensemble", href: "/dashboard" },
  { label: "Inbox", href: "/dashboard#attention" },
  { label: "CRM", href: "/dashboard/crm" },
  { label: "Workflows", href: "/dashboard#performance" },
  { label: "Paramètres", href: "/dashboard#health" },
];

export function DashboardNavigation({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();

  return (
    <nav aria-label={mobile ? "Navigation mobile" : "Navigation principale"}>
      <ul className={mobile ? "grid gap-1 py-2" : "mt-3 space-y-1"}>
        {navigation.map((item, index) => {
          const active =
            item.href === "/dashboard"
              ? pathname === "/dashboard"
              : item.href.includes("#")
                ? false
                : pathname.startsWith(item.href);
          return (
            <li key={item.label}>
              <Link
                href={item.href}
                className={`dashboard-nav-item ${active ? "dashboard-nav-item-active" : ""}`}
                aria-current={active ? "page" : undefined}
              >
                <span className="nav-index" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
