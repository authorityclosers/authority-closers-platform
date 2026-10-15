"use client";

/**
 * The Admin company view's controls: organisation, period and narrowing,
 * kept in the address; and the refresh that prepares new calls (one bounded
 * batch per request) before the figures are read again.
 */
import { RotateCw } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Segmented } from "@/app/ui/kit-client";

import {
  INSIGHTS_PATH,
  OUTCOMES,
  RANGES,
  type Filters,
  type Insights,
  type Organisation,
} from "./company-data";
import styles from "./company.module.css";

function addressOf(
  organisation: string | null,
  filters: Filters,
  next: Partial<Filters & { organisation: string | null }>,
) {
  const merged = { organisation, ...filters, ...next };
  const query = new URLSearchParams();
  if (merged.organisation) query.set("organisation", merged.organisation);
  if (merged.range !== "90d") query.set("range", merged.range);
  for (const name of ["person", "team", "outcome", "language"] as const) {
    const value = merged[name];
    if (value) query.set(name, value);
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

export function CompanyControls({
  organisations,
  organisation,
  filters,
  facets,
}: {
  organisations: Organisation[];
  organisation: string | null;
  filters: Filters;
  facets: Insights["facets"] | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const go = (next: Partial<Filters & { organisation: string | null }>) =>
    router.push(`${pathname}${addressOf(organisation, filters, next)}`, {
      scroll: false,
    });
  return (
    <div
      className={styles.controls}
      role="group"
      aria-label="Company view filters"
    >
      <select
        className={styles.select}
        aria-label="Organisation"
        value={organisation ?? ""}
        onChange={(event) =>
          go({
            organisation: event.target.value || null,
            person: null,
            team: null,
            language: null,
          })
        }
      >
        {organisations.map((item) => (
          <option key={item.id} value={item.id}>
            {item.sandbox ? `${item.name} (synthetic)` : item.name}
          </option>
        ))}
      </select>
      <Segmented
        label="Period"
        items={RANGES.map((item) => ({ key: item.key, label: item.label }))}
        value={filters.range}
        onChange={(range) => go({ range })}
      />
      {facets ? (
        <select
          className={styles.select}
          aria-label="Person"
          value={filters.person ?? ""}
          onChange={(event) => go({ person: event.target.value || null })}
        >
          <option value="">Everyone</option>
          {facets.people.map((person) => (
            <option key={person.key} value={person.key}>
              {person.name}
            </option>
          ))}
        </select>
      ) : null}
      {facets?.teams.length ? (
        <select
          className={styles.select}
          aria-label="Team"
          value={filters.team ?? ""}
          onChange={(event) => go({ team: event.target.value || null })}
        >
          <option value="">All teams</option>
          {facets.teams.map((team) => (
            <option key={team.key} value={team.key}>
              {team.name}
            </option>
          ))}
        </select>
      ) : null}
      <select
        className={styles.select}
        aria-label="Outcome"
        value={filters.outcome ?? ""}
        onChange={(event) =>
          go({ outcome: (event.target.value || null) as Filters["outcome"] })
        }
      >
        <option value="">Any outcome</option>
        {OUTCOMES.map((outcome) => (
          <option key={outcome.key} value={outcome.key}>
            {outcome.label}
          </option>
        ))}
      </select>
      {facets && facets.languages.length > 1 ? (
        <select
          className={styles.select}
          aria-label="Language"
          value={filters.language ?? ""}
          onChange={(event) => go({ language: event.target.value || null })}
        >
          <option value="">Any language</option>
          {facets.languages.map((language) => (
            <option key={language.key} value={language.key}>
              {language.label}
            </option>
          ))}
        </select>
      ) : null}
    </div>
  );
}

/** Prepares new calls (bounded batches), then reads the page again. */
export function PrepareCalls({
  organisation,
  pending,
}: {
  organisation: string;
  pending: number;
}) {
  const router = useRouter();
  const [left, setLeft] = useState(pending);
  const [failed, setFailed] = useState(false);
  // Each run owns its loop; leaving the page (or another organisation, which
  // remounts this by key) cancels it.
  useEffect(() => {
    if (pending <= 0) return;
    let cancelled = false;
    (async () => {
      let remaining = pending;
      try {
        for (
          let round = 0;
          round < 60 && remaining > 0 && !cancelled;
          round += 1
        ) {
          const response = await fetch(
            `${INSIGHTS_PATH}/refresh?organisation=${encodeURIComponent(organisation)}`,
            {
              method: "POST",
              credentials: "same-origin",
              cache: "no-store",
              redirect: "error",
              headers: { accept: "application/json" },
            },
          );
          if (!response.ok) throw new Error(String(response.status));
          const body = (await response.json()) as {
            projected?: number;
            pending?: number;
          };
          remaining = typeof body.pending === "number" ? body.pending : 0;
          if (!cancelled) setLeft(remaining);
          if (!body.projected) break;
        }
        if (!cancelled) router.refresh();
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [organisation, pending, router]);
  if (pending <= 0) return null;
  return (
    <p className={styles.preparing} role="status">
      <RotateCw
        size={13}
        aria-hidden="true"
        className={failed ? undefined : styles.spin}
      />
      {failed
        ? "Some new calls aren't counted yet; the figures show the calls prepared so far."
        : `Preparing ${left.toLocaleString("en-IN")} new calls for these figures…`}
    </p>
  );
}
