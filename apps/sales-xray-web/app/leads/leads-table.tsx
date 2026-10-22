"use client";

/**
 * Leads as a table on a computer (owner P0, 23 Oct 2026: "a Notion-like table"):
 * one lead per line with its stage, pipeline, owner, source, next step and last
 * call, sortable by any column. The list's own rows, paging, Select and row keys
 * (J/K, Enter) carry over. Phones keep the two-line rows: nothing scrolls sideways.
 * Cells change in place (table-edit.tsx); arrow keys move between them.
 */

import { ArrowDown, ArrowUp, Pencil } from "lucide-react";
import {
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type RefObject,
} from "react";

import { displayName } from "../display-name";
import { when, type LeadRow } from "./leads-client";
import { QuickAddRow, type PasteRows } from "./quick-add";
import {
  EDIT_COLUMNS,
  PickEditor,
  TextEditor,
  useLeadEdits,
  type EditColumn,
  type EditRights,
  type Move,
} from "./table-edit";
import styles from "./leads-table.module.css";

// Wide enough beside the sidebar for every column to read (1000 px left
// names at "Asha F…"); narrower screens keep the list.
const WIDE = "(min-width: 1100px)";
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
  edit = null,
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
  quickAdd?: {
    pipeline: string | null;
    onAdded: () => void;
    onPasteRows?: PasteRows;
  } | null;
  /** Who may change what in place; none while selecting. */
  edit?: EditRights | null;
}) {
  const [sort, setSort] = useState<{ by: Column; down: boolean } | null>(null);
  const grid = useRef<HTMLTableElement>(null);
  const edits = useLeadEdits(rows, selecting ? null : edit, pipelineNames);
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
    if (!sort) return edits.shown;
    const sign = sort.down ? -1 : 1;
    return [...edits.shown].sort((a, b) => {
      const x = sortKey(a, sort.by);
      const y = sortKey(b, sort.by);
      if (x === y) return 0;
      return (x < y ? -1 : 1) * sign;
    });
  }, [edits.shown, sort]);
  const now = new Date();
  const editColumns = columns.filter((column): column is EditColumn =>
    EDIT_COLUMNS.has(column),
  );
  const cellKey = (leadId: string, column: Column) => `${leadId}:${column}`;
  const focusCell = (leadId: string, column: Column) =>
    window.setTimeout(() =>
      grid.current
        ?.querySelector<HTMLElement>(`[data-cell="${cellKey(leadId, column)}"]`)
        ?.focus(),
    );

  /** The next cell to edit: down the column, or along the row and on. */
  const after = (leadId: string, column: EditColumn, move: Move) => {
    const at = shown.findIndex((row) => row.lead_id === leadId);
    if (move === "down") {
      const row = shown.slice(at + 1).find((next) => edits.can(next, column));
      return row ? { row, column } : null;
    }
    const step = move === "next" ? 1 : -1;
    let index = editColumns.indexOf(column) + step;
    for (let line = at; line >= 0 && line < shown.length; line += step) {
      for (; index >= 0 && index < editColumns.length; index += step)
        if (edits.can(shown[line], editColumns[index]))
          return { row: shown[line], column: editColumns[index] };
      index = step > 0 ? 0 : editColumns.length - 1;
    }
    return null;
  };

  const done =
    (row: LeadRow, column: EditColumn) =>
    (value: string | null, move: Move, refocus: boolean) => {
      if (value !== null) edits.commit(row, column, value);
      const next = move ? after(row.lead_id, column, move) : null;
      if (next) edits.start(next.row, next.column);
      else {
        edits.stop();
        if (refocus) focusCell(row.lead_id, column);
      }
    };

  const editor = (row: LeadRow, column: EditColumn) => {
    const label = `${LABELS[column]} of ${displayName(row.name)}`;
    if (column === "name" || column === "phone")
      return (
        <TextEditor
          initial={column === "name" ? row.name : ""}
          phoneOf={column === "phone" ? row.lead_id : undefined}
          label={label}
          onDone={done(row, column)}
        />
      );
    return (
      <PickEditor
        value={edits.current(row, column)}
        options={edits.choices(row, column)}
        open={edits.editing?.open ?? false}
        label={label}
        onDone={done(row, column)}
      />
    );
  };

  /** Arrow keys between cells (not while typing in one). */
  const onGridKey = (event: KeyboardEvent<HTMLTableElement>) => {
    if (!event.key.startsWith("Arrow")) return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
      return;
    const target = event.target as HTMLElement;
    if (target.closest("input, select, textarea")) return;
    const here = target.closest<HTMLElement>("[data-cell]")?.dataset.cell;
    if (!here) return;
    const [leadId, from] = here.split(":");
    let line = shown.findIndex((row) => row.lead_id === leadId);
    let index = columns.indexOf(from as Column);
    const down =
      event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    const across =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    event.preventDefault();
    for (;;) {
      line += down;
      index += across;
      if (line < 0 || line >= shown.length) return;
      if (index < 0 || index >= columns.length) return;
      const next = grid.current?.querySelector<HTMLElement>(
        `[data-cell="${cellKey(shown[line].lead_id, columns[index])}"]`,
      );
      if (next) {
        next.focus();
        next.scrollIntoView?.({ block: "nearest" });
        return;
      }
    }
  };

  const cell = (row: LeadRow, column: Column) => {
    switch (column) {
      case "name":
        return (
          <span className={styles.nameCell}>
            <button
              type="button"
              className={styles.name}
              data-row-key={row.lead_id}
              data-cell={cellKey(row.lead_id, "name")}
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
            {edits.can(row, "name") ? (
              <button
                type="button"
                className={styles.rename}
                aria-label={`Rename ${displayName(row.name)}`}
                onClick={(event) => {
                  event.stopPropagation();
                  edits.start(row, "name");
                }}
              >
                <Pencil size={13} aria-hidden="true" />
              </button>
            ) : null}
          </span>
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
      <table
        ref={grid}
        className={styles.table}
        aria-label="Leads"
        onKeyDown={onGridKey}
      >
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
              {columns.map((column) => {
                const editable =
                  EDIT_COLUMNS.has(column) &&
                  edits.can(row, column as EditColumn);
                if (
                  editable &&
                  edits.editing?.leadId === row.lead_id &&
                  edits.editing.column === column
                )
                  return (
                    <td
                      key={column}
                      data-column={column}
                      data-editing=""
                      onClick={(event) => event.stopPropagation()}
                    >
                      {editor(row, column as EditColumn)}
                    </td>
                  );
                return (
                  <td key={column} data-column={column}>
                    {editable && column !== "name" ? (
                      <button
                        type="button"
                        className={styles.cell}
                        data-cell={cellKey(row.lead_id, column)}
                        onClick={(event) => {
                          event.stopPropagation();
                          edits.start(row, column as EditColumn, true);
                        }}
                      >
                        {cell(row, column)}
                        <span className={styles.srOnly}>
                          {`, change ${LABELS[column].toLowerCase()}`}
                        </span>
                      </button>
                    ) : (
                      cell(row, column)
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
        {quickAdd ? (
          <tfoot>
            <QuickAddRow
              pipeline={quickAdd.pipeline}
              onAdded={quickAdd.onAdded}
              onPasteRows={quickAdd.onPasteRows}
              before={selecting ? 1 : 0}
              after={columns.length - 3}
            />
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
