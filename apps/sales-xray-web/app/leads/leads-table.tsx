"use client";

/**
 * Leads as a table on a computer (owner P0, 23 Oct 2026: "a Notion-like table"):
 * one lead per line with its stage, pipeline, owner, source, next step and last
 * call, sortable by any column. The list's own rows, paging, Select and row keys
 * (J/K, Enter) carry over. Phones keep the two-line rows: nothing scrolls sideways.
 */

import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState, useSyncExternalStore, type RefObject } from "react";

import { displayName } from "../display-name";
import { when, type LeadRow } from "./leads-client";
import { QuickAddRow } from "./quick-add";
import styles from "./leads-table.module.css";

const WIDE = "(min-width: 900px)";
const onWidth = (change: () => void) => {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia(WIDE);
  query.addEventListener("change", change);
  return () => query.removeEventListener("change", change);
};

/** A computer-wide screen: only there is the table offered. */
export function useWideScreen(): boolean {
  return useSyncExternalStore(
    onWidth,
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia(WIDE).matches,
    () => false,
  );
}

type Column =
  | "name"
  | "phone"
  | "stage"
  | "pipeline"
  | "owner"
  | "source"
  | "next"
  | "last";

const LABELS: Record<Column, string> = {
  name: "Name",
  phone: "Phone",
  stage: "Stage",
  pipeline: "Pipeline",
  owner: "Owner",
  source: "Source",
  next: "Next action",
  last: "Last call",
};

/** Stages in the order a lead moves through them, for sorting. */
const STAGE_ORDER = [
  "new",
  "not_connected",
  "follow_up",
  "interested",
  "won",
  "lost",
];

const lastCall = (row: LeadRow) =>
  row.last_result_label
    ? row.calls
      ? `${row.last_result_label} · ${row.calls} ${row.calls === 1 ? "call" : "calls"}`
      : row.last_result_label
    : row.calls
      ? `${row.calls} ${row.calls === 1 ? "call" : "calls"}`
      : "Not called";

/** A column's sort key: text sorts by words, times and stages by their order. */
function sortKey(row: LeadRow, by: Column): string | number {
  switch (by) {
    case "name":
      return displayName(row.name).toLowerCase();
    case "phone":
      return row.phone_last4 ?? "";
    case "stage":
      return STAGE_ORDER.indexOf(row.stage);
    case "pipeline":
      return row.pipeline ?? "";
    case "owner":
      return row.owner_name ? displayName(row.owner_name).toLowerCase() : "~";
    case "source":
      return (row.source_label ?? "").toLowerCase();
    case "next":
      // No next step sorts last either way round.
      return row.next_action_at
        ? new Date(row.next_action_at).getTime()
        : Number.MAX_SAFE_INTEGER;
    case "last":
      return row.calls;
  }
}

export function LeadsTable({
  rows,
  onOpen,
  showOwner,
  pipelineNames = null,
  selecting = false,
  chosen,
  onToggle,
  keysRef,
  quickAdd = null,
}: {
  rows: LeadRow[];
  onOpen: (leadId: string) => void;
  /** Whose leads: everyone's or no owner's lists show the Owner column. */
  showOwner: boolean;
  /** Several pipelines: each one's name, and the Pipeline column. */
  pipelineNames?: ReadonlyMap<string, string> | null;
  /** Select (owners and admins): a tick column, and a line's tap ticks it. */
  selecting?: boolean;
  chosen?: ReadonlyMap<string, string>;
  onToggle?: (row: LeadRow) => void;
  /** The list's row keys (J/K, Enter) read the table's rows here. */
  keysRef?: RefObject<HTMLDivElement | null>;
  /** Quick add as the last line: the pipeline it adds to, and after adding. */
  quickAdd?: { pipeline: string | null; onAdded: () => void } | null;
}) {
  const [sort, setSort] = useState<{ by: Column; down: boolean } | null>(null);
  const columns: Column[] = [
    "name",
    "phone",
    "stage",
    ...(pipelineNames ? (["pipeline"] as const) : []),
    ...(showOwner ? (["owner"] as const) : []),
    "source",
    "next",
    "last",
  ];
  const shown = useMemo(() => {
    if (!sort) return rows;
    const sign = sort.down ? -1 : 1;
    return [...rows].sort((a, b) => {
      const x = sortKey(a, sort.by);
      const y = sortKey(b, sort.by);
      if (x === y) return 0;
      return (x < y ? -1 : 1) * sign;
    });
  }, [rows, sort]);
  const now = new Date();

  const cell = (row: LeadRow, column: Column) => {
    switch (column) {
      case "name":
        return (
          <button
            type="button"
            className={styles.name}
            data-row-key={row.lead_id}
            onClick={(event) => {
              event.stopPropagation();
              if (selecting) onToggle?.(row);
              else onOpen(row.lead_id);
            }}
          >
            <strong>{displayName(row.name)}</strong>
            {row.company || row.city ? (
              <small>{row.company ?? row.city}</small>
            ) : null}
          </button>
        );
      case "phone":
        return row.phone_last4 ? (
          <span className={styles.phone}>{`•• ${row.phone_last4}`}</span>
        ) : (
          <span className={styles.quiet}>No number</span>
        );
      case "stage":
        return <span className={styles.stage}>{row.stage_label}</span>;
      case "pipeline":
        return pipelineNames?.get(row.pipeline ?? "main") ?? row.pipeline;
      case "owner":
        return row.owner_name ? (
          displayName(row.owner_name)
        ) : (
          <span className={styles.quiet}>No owner</span>
        );
      case "source":
        return row.source_label;
      case "next":
        return row.next_action_at ? (
          <span data-late={row.overdue ? "" : undefined}>
            {when(row.next_action_at, now)}
          </span>
        ) : (
          <span className={styles.quiet}>None</span>
        );
      case "last":
        return lastCall(row);
    }
  };

  return (
    <div className={styles.wrap} ref={keysRef}>
      <table className={styles.table} aria-label="Leads">
        <thead>
          <tr>
            {selecting ? (
              <th scope="col" className={styles.pick}>
                <span className={styles.srOnly}>Select</span>
              </th>
            ) : null}
            {columns.map((column) => {
              const sorted = sort?.by === column;
              return (
                <th
                  key={column}
                  scope="col"
                  data-column={column}
                  aria-sort={
                    sorted ? (sort.down ? "descending" : "ascending") : "none"
                  }
                >
                  <button
                    type="button"
                    className={styles.sort}
                    onClick={() =>
                      setSort((current) =>
                        current?.by === column
                          ? current.down
                            ? null
                            : { by: column, down: true }
                          : { by: column, down: false },
                      )
                    }
                  >
                    {LABELS[column]}
                    {sorted ? (
                      sort.down ? (
                        <ArrowDown size={13} aria-hidden="true" />
                      ) : (
                        <ArrowUp size={13} aria-hidden="true" />
                      )
                    ) : null}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr
              key={row.lead_id}
              data-selected={chosen?.has(row.lead_id) ? "" : undefined}
              onClick={() =>
                selecting ? onToggle?.(row) : onOpen(row.lead_id)
              }
            >
              {selecting ? (
                <td className={styles.pick}>
                  <input
                    type="checkbox"
                    checked={chosen?.has(row.lead_id) ?? false}
                    onChange={() => onToggle?.(row)}
                    onClick={(event) => event.stopPropagation()}
                    aria-label={`Select ${displayName(row.name)}`}
                  />
                </td>
              ) : null}
              {columns.map((column) => (
                <td key={column} data-column={column}>
                  {cell(row, column)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {quickAdd ? (
          <tfoot>
            <QuickAddRow
              pipeline={quickAdd.pipeline}
              onAdded={quickAdd.onAdded}
              before={selecting ? 1 : 0}
              after={columns.length - 3}
            />
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
