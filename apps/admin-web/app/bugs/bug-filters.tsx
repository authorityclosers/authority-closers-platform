"use client";

/**
 * The Bugs list's filters: severity, area and organisation. Each change
 * rewrites the address (dropping the page), so the server renders the
 * filtered list and links keep the view.
 */
import { X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useTransition } from "react";

import { kitStyles, Toolbar } from "../ui/kit";
import {
  AREAS,
  AREA_LABEL,
  SEVERITIES,
  SEVERITY_LABEL,
  bugQuery,
  type BugFilters as Filters,
  type BugPage,
} from "./bugs-data";
import styles from "./bugs.module.css";

export function BugFilters({
  filters,
  organisations,
}: {
  filters: Filters;
  organisations: BugPage["organisations"];
}) {
  const router = useRouter();
  const pathname = usePathname() ?? "/bugs";
  const [pending, start] = useTransition();
  const go = (next: Filters) => {
    const query = bugQuery(next, ["offset"]);
    start(() =>
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false }),
    );
  };
  const set = (key: "severity" | "area" | "organisation", value: string) =>
    go({ ...filters, [key]: value || undefined } as Filters);
  const active = Boolean(
    filters.severity || filters.area || filters.organisation,
  );
  return (
    <Toolbar label="Filter bug reports">
      <select
        aria-label="Severity"
        className={styles.filterSelect}
        value={filters.severity ?? ""}
        onChange={(event) => set("severity", event.target.value)}
      >
        <option value="">Severity: all</option>
        <option value="none">Not set yet</option>
        {SEVERITIES.map((severity) => (
          <option key={severity} value={severity}>
            {SEVERITY_LABEL[severity]}
          </option>
        ))}
      </select>
      <select
        aria-label="Area"
        className={styles.filterSelect}
        value={filters.area ?? ""}
        onChange={(event) => set("area", event.target.value)}
      >
        <option value="">Area: all</option>
        {AREAS.map((area) => (
          <option key={area} value={area}>
            {AREA_LABEL[area]}
          </option>
        ))}
      </select>
      <select
        aria-label="Organisation"
        className={styles.filterSelect}
        value={filters.organisation ?? ""}
        onChange={(event) => set("organisation", event.target.value)}
      >
        <option value="">Organisation: all</option>
        {filters.organisation &&
        !organisations.some((item) => item.id === filters.organisation) ? (
          <option value={filters.organisation}>Selected</option>
        ) : null}
        {organisations.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name} ({item.count})
          </option>
        ))}
      </select>
      {active ? (
        <button
          type="button"
          className={kitStyles.button}
          data-variant="ghost"
          onClick={() => go({ view: filters.view })}
        >
          <X size={14} aria-hidden="true" />
          Clear filters
        </button>
      ) : null}
      {pending ? (
        <span className={kitStyles.muted} role="status">
          Loading…
        </span>
      ) : null}
    </Toolbar>
  );
}
