"use client";

/**
 * The queue's filter bar. Each change rewrites the address (dropping the page
 * cursor), so the server renders the filtered queue and links keep the view.
 */
import { SlidersHorizontal, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { kitStyles, Toolbar } from "../ui/kit";
import {
  CALL_STATUSES,
  STATUS_LABEL,
  languageLabel,
  type Queue,
} from "./call-data";
import styles from "./calls.module.css";
import { filterQuery, type QueueFilters as Filters } from "./queue-query";

export function QueueFilters({
  filters,
  facets,
}: {
  filters: Filters;
  facets: Queue["facets"];
}) {
  const router = useRouter();
  const pathname = usePathname() ?? "/calls";
  const [pending, start] = useTransition();
  // Phones keep the filters behind one button so the queue starts on screen.
  const [shown, setShown] = useState(false);
  const set = (key: keyof Filters, value: string) => {
    const next = { ...filters, [key]: value || undefined };
    const query = filterQuery(next, ["cursor"]);
    start(() =>
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false }),
    );
  };
  const select = (
    key: "organisation" | "rep" | "language" | "provider" | "prompt",
    label: string,
    options: Queue["facets"]["organisations"],
    name: (value: string, fallback: string) => string = (_value, fallback) =>
      fallback,
  ) => (
    <select
      aria-label={label}
      title={label}
      className={styles.filterSelect}
      value={filters[key] ?? ""}
      onChange={(event) => set(key, event.target.value)}
    >
      <option value="">{label}: all</option>
      {/* Keep a chosen value listed even when the current window has no calls for it. */}
      {filters[key] &&
      !options.some((option) => option.value === filters[key]) ? (
        <option value={filters[key]}>{name(filters[key]!, "Selected")}</option>
      ) : null}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {name(option.value, option.label)} ({option.count})
        </option>
      ))}
    </select>
  );
  const active = Object.entries(filters).some(
    ([key, value]) => key !== "review" && key !== "cursor" && value,
  );
  const chosen = Object.entries(filters).filter(
    ([key, value]) => key !== "review" && key !== "cursor" && value,
  ).length;
  return (
    <div className={styles.filterArea} data-shown={shown ? "" : undefined}>
      <button
        type="button"
        className={`${kitStyles.button} ${styles.filterToggle}`}
        aria-expanded={shown}
        onClick={() => setShown((value) => !value)}
      >
        <SlidersHorizontal size={14} aria-hidden="true" />
        {chosen ? `Filters · ${chosen}` : "Filters"}
      </button>
      <Toolbar label="Filter calls">
        <select
          aria-label="Analysis"
          className={styles.filterSelect}
          value={filters.status ?? ""}
          onChange={(event) => set("status", event.target.value)}
        >
          <option value="">Analysis: all</option>
          {CALL_STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABEL[status]}
            </option>
          ))}
        </select>
        {select("organisation", "Organisation", facets.organisations)}
        {select("rep", "Rep", facets.reps)}
        {select("language", "Language", facets.languages, (value) =>
          languageLabel(value),
        )}
        {select("provider", "Provider", facets.providers)}
        {select("prompt", "Prompt", facets.prompts, (value) => value)}
        <label className={styles.dateFilter}>
          <span>From</span>
          <input
            type="date"
            aria-label="Uploaded from"
            value={filters.since ?? ""}
            max={filters.until || undefined}
            onChange={(event) => set("since", event.target.value)}
          />
        </label>
        <label className={styles.dateFilter}>
          <span>To</span>
          <input
            type="date"
            aria-label="Uploaded until"
            value={filters.until ?? ""}
            min={filters.since || undefined}
            onChange={(event) => set("until", event.target.value)}
          />
        </label>
        {active ? (
          <button
            type="button"
            className={kitStyles.button}
            data-variant="ghost"
            onClick={() => {
              const query = filterQuery({ review: filters.review });
              start(() =>
                router.push(query ? `${pathname}?${query}` : pathname, {
                  scroll: false,
                }),
              );
            }}
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
    </div>
  );
}
