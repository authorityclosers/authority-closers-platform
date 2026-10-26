"use client";

/**
 * A seller's day at a glance (owner, #18, 26 Oct 2026: "the homepage is the
 * same as the Leads section; give it a dashboard view"): four tiles, each one
 * tap into the Leads it counts, and their open leads by stage. Only real
 * numbers: a tile with nothing shows 0.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { readLeads } from "../leads/leads-client";
import { readJourney } from "../leads/journey/journey-client";
import { Skeleton } from "../ui/kit";
import styles from "./day-board.module.css";

export type DayCounts = {
  overdue: number;
  dueToday: number;
  fresh: number;
  calls: number;
};

/** Overdue, Due today, New leads and Calls today, each opening its list. */
export function DayTiles({ counts }: { counts: DayCounts }) {
  const tiles = [
    {
      key: "late",
      label: "Overdue",
      value: counts.overdue,
      href: "/leads?tab=all&due=late",
      bad: counts.overdue > 0,
    },
    {
      key: "today",
      label: "Due today",
      value: counts.dueToday,
      href: "/leads?tab=all&due=today",
      bad: false,
    },
    {
      key: "new",
      label: "New leads",
      value: counts.fresh,
      href: "/leads?tab=all&stage=new",
      bad: false,
    },
    {
      key: "calls",
      label: "Calls today",
      value: counts.calls,
      href: "/analysis/calls",
      bad: false,
    },
  ];
  return (
    <ul className={styles.tiles} aria-label="Your day">
      {tiles.map((tile) => (
        <li key={tile.key}>
          <Link
            className={styles.tile}
            href={tile.href}
            data-tone={tile.bad ? "bad" : undefined}
          >
            <strong>{tile.value}</strong>
            <span>{tile.label}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

type StageRow = { key: string; label: string; count: number };

/** Your open leads by the organisation's stages, each opening that stage. */
export function MyStages() {
  const [rows, setRows] = useState<StageRow[] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      readLeads({ scope: "mine", stage: "open" }, controller.signal),
      readJourney(),
    ]).then(
      ([page, journey]) => {
        if (controller.signal.aborted) return;
        const counts = page.stage_counts ?? {};
        setRows(
          journey.stages
            .filter((stage) => !stage.archived)
            .map((stage) => ({
              key: stage.key,
              label: stage.label,
              count: counts[stage.key] ?? 0,
            })),
        );
      },
      () => {
        if (!controller.signal.aborted) setRows([]);
      },
    );
    return () => controller.abort();
  }, []);
  if (rows !== null && !rows.length) return null;
  const most = Math.max(1, ...(rows ?? []).map((row) => row.count));
  return (
    <section className={styles.stages} aria-labelledby="my-stages-title">
      <h2 id="my-stages-title">Your leads by stage</h2>
      {rows === null ? (
        <div className={styles.skeleton} aria-busy="true">
          <Skeleton height={14} />
          <Skeleton height={14} />
          <Skeleton height={14} />
        </div>
      ) : (
        <ul className={styles.stageList}>
          {rows.map((row) => (
            <li key={row.key}>
              <Link
                href={`/leads?tab=all&stage=${encodeURIComponent(row.key)}`}
              >
                <span className={styles.stageLabel}>{row.label}</span>
                <span className={styles.track} aria-hidden="true">
                  <span
                    className={styles.bar}
                    style={{
                      width: row.count
                        ? `${Math.max(3, (row.count / most) * 100)}%`
                        : 0,
                    }}
                  />
                </span>
                <strong className={styles.stageCount}>{row.count}</strong>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
