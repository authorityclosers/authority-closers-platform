"use client";

/**
 * Follow-ups by day (Leads L1, chosen by the owner 8 Nov 2026; docs/design/
 * screens/leads/spec.md §3): one card per group, Overdue, Due Today and
 * Upcoming, in time order, each with its name and count at its top. A group
 * past five rows ends in "Show all N".
 *
 * The groups are the server's own split (work_views.in_when: planned before
 * today, today, or later, in India's day), so their counts add up to the tab's.
 * The list arrives next due first, so every group before the last one read is
 * whole; past the last, the server is asked for a group's count alone.
 */

import { useEffect, useRef, useState, type ReactNode, type Ref } from "react";

import { readLeads, type FollowUpWhen, type LeadRow } from "./leads-client";
import styles from "./leads.module.css";
import { FOLLOW_UPS } from "./work-views";

const ORDER: readonly FollowUpWhen[] = ["overdue", "today", "upcoming"];
/** Rows a group shows before "Show all". */
export const FIRST_ROWS = 5;

const IST_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** Which group a follow-up is in: its planned day against today, in India. */
export function dayOf(row: LeadRow, now: Date = new Date()): FollowUpWhen {
  if (!row.next_action_at) return "upcoming";
  const day = IST_DAY.format(new Date(row.next_action_at));
  const today = IST_DAY.format(now);
  return day < today ? "overdue" : day === today ? "today" : "upcoming";
}

export type DayRows = Readonly<Record<FollowUpWhen, readonly LeadRow[]>> & {
  /** The group of the last row read, or null for none. */
  last: FollowUpWhen | null;
};

/** The rows in their groups, each in the list's order. */
export function dayGroups(
  rows: readonly LeadRow[],
  now: Date = new Date(),
): DayRows {
  const groups: Record<FollowUpWhen, LeadRow[]> = {
    overdue: [],
    today: [],
    upcoming: [],
  };
  for (const row of rows) groups[dayOf(row, now)].push(row);
  const end = rows.at(-1);
  return { ...groups, last: end ? dayOf(end, now) : null };
}

/**
 * Each group's count, or null while it isn't known. Every row read: their
 * own counts. Otherwise the groups before the last one read are whole; a count
 * the server gave stands in for one that isn't; and Upcoming, last, is the
 * rest of the list's total.
 */
export function dayCounts(
  groups: DayRows,
  complete: boolean,
  total: number | null,
  known: Partial<Record<FollowUpWhen, number>> = {},
): Record<FollowUpWhen, number | null> {
  const out: Record<FollowUpWhen, number | null> = {
    overdue: null,
    today: null,
    upcoming: null,
  };
  const lastAt = groups.last ? ORDER.indexOf(groups.last) : -1;
  ORDER.forEach((key, at) => {
    if (complete || at < lastAt) out[key] = groups[key].length;
    else if (known[key] !== undefined) out[key] = known[key] ?? null;
  });
  if (
    out.upcoming === null &&
    out.overdue !== null &&
    out.today !== null &&
    total !== null
  )
    out.upcoming = Math.max(0, total - out.overdue - out.today);
  return out;
}

/** The groups whose count only the server can give (Upcoming is the rest). */
export function countsToAsk(
  counts: Record<FollowUpWhen, number | null>,
): FollowUpWhen[] {
  return (["overdue", "today"] as const).filter((key) => counts[key] === null);
}

type Ask = Parameters<typeof readLeads>[0];

/** Each asked group's count, from the server, for the list read as `key`. */
export function useDayTotals(
  key: string,
  need: readonly FollowUpWhen[],
  ask: Ask,
): Partial<Record<FollowUpWhen, number>> {
  const [got, setGot] = useState<{
    key: string;
    totals: Partial<Record<FollowUpWhen, number>>;
  }>({ key: "", totals: {} });
  const latest = useRef(ask);
  useEffect(() => {
    latest.current = ask;
  });
  const asked = need.join(" ");
  useEffect(() => {
    if (!asked) return;
    const base = latest.current;
    const controller = new AbortController();
    for (const when of asked.split(" ") as FollowUpWhen[])
      readLeads({ ...base, more: { ...base.more, when } }, controller.signal)
        .then((page) =>
          setGot((now) => ({
            key,
            totals: {
              ...(now.key === key ? now.totals : {}),
              [when]: page.total,
            },
          })),
        )
        // Not counted: that group's header shows no number.
        .catch(() => undefined);
    return () => controller.abort();
  }, [key, asked]);
  return got.key === key ? got.totals : {};
}

export function DayGroups({
  groups,
  counts,
  render,
  onShowAll,
  boxRef,
}: {
  groups: DayRows;
  counts: Record<FollowUpWhen, number | null>;
  /** One row: its place in its group and the group's count. */
  render: (row: LeadRow, index: number, count: number) => ReactNode;
  /** A group opened past what is read: the list reads more. */
  onShowAll?: () => void;
  boxRef?: Ref<HTMLDivElement>;
}) {
  const [open, setOpen] = useState<ReadonlySet<FollowUpWhen>>(new Set());
  return (
    <div ref={boxRef} className={styles.dayGroups}>
      {ORDER.map((key) => {
        const rows = groups[key];
        const count = counts[key];
        if (!rows.length && !count) return null;
        const label = FOLLOW_UPS.find((item) => item.key === key)?.label ?? key;
        const opened = open.has(key);
        const shown = opened ? rows : rows.slice(0, FIRST_ROWS);
        const all = count ?? rows.length;
        return (
          <section key={key} className={styles.dayCard} aria-label={label}>
            <h3 className={styles.dayHead}>
              {label}
              {count !== null ? (
                <span className={styles.dayCount}>{count}</span>
              ) : null}
            </h3>
            {shown.length ? (
              <ul className={styles.leadList} aria-label={label}>
                {shown.map((row, index) => render(row, index, all))}
              </ul>
            ) : null}
            {!opened && all > FIRST_ROWS ? (
              <button
                type="button"
                className={styles.dayAll}
                onClick={() => {
                  setOpen((now) => new Set(now).add(key));
                  if (rows.length < all) onShowAll?.();
                }}
              >
                {count !== null ? `Show all ${count}` : "Show all"}
              </button>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
