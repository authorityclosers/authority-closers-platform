"use client";

/**
 * Leads as a table on a computer (owner P0, 23 Oct 2026: "a Notion-like table"):
 * one lead per line with its stage, pipeline, owner, source, next step and last
 * call, sortable by any column. The list's own rows, paging, Select and row keys
 * (J/K, Enter) carry over. Phones keep the two-line rows: nothing scrolls sideways.
 * Cells change in place (table-edit.tsx); arrow keys move between them.
 * Lead OS (24 Oct 2026): how long each lead has sat in its stage, its last
 * contact, its Lost or Junk reason and when it came in; a column picker that
 * this browser remembers; a stage that asks for something opens the stage sheet.
 * Phones and narrow panes (owner, 25 Oct 2026: "sideways scrolling is hard"):
 * nothing scrolls sideways. Name and as many key columns as the pane holds
 * stay in the row; the rest open under it from the row's chevron.
 */

import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Columns3,
  Pencil,
} from "lucide-react";
import {
  Fragment,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { displayName } from "../display-name";
import {
  ago,
  readLead,
  when,
  type LeadRow,
  type ListSort,
} from "./leads-client";
import type { MoveOption } from "./pipeline/pipeline-client";
import { StageSheet } from "./pipeline/stage-sheet";
import { QuickAddBar, QuickAddRow, type PasteRows } from "./quick-add";
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
  | "last"
  | "age"
  | "contact"
  | "reason"
  | "created";

const LABELS: Record<Column, string> = {
  name: "Name",
  phone: "Phone",
  stage: "Stage",
  pipeline: "Pipeline",
  owner: "Owner",
  source: "Source",
  next: "Next action",
  last: "Last call",
  age: "In stage",
  contact: "Last contact",
  reason: "Reason",
  created: "Added",
};

/** Heads whose sort the server answers over the whole list. */
const SERVER_SORT: Partial<Record<Column, ListSort>> = {
  name: "name",
  next: "next_action",
  contact: "last_contact",
  created: "created",
};

/** Columns a person can show or hide (Name and Stage always show). */
export const OPTIONAL: Column[] = [
  "phone",
  "source",
  "next",
  "last",
  "age",
  "contact",
  "reason",
  "created",
];
const SHOWN_AT_FIRST: ReadonlySet<Column> = new Set([
  "phone",
  "source",
  "next",
  "last",
  "age",
]);
const COLUMNS_KEY = "sx-leads-table-columns";

function readShown(): ReadonlySet<Column> {
  try {
    const raw = window.localStorage.getItem(COLUMNS_KEY);
    const list = raw ? (JSON.parse(raw) as unknown) : null;
    if (Array.isArray(list))
      return new Set(
        list.filter((item): item is Column =>
          OPTIONAL.includes(item as Column),
        ),
      );
  } catch {
    /* private window: the first columns */
  }
  return SHOWN_AT_FIRST;
}

function keepShown(shown: ReadonlySet<Column>) {
  try {
    window.localStorage.setItem(COLUMNS_KEY, JSON.stringify([...shown]));
  } catch {
    /* not kept: this browser stores nothing */
  }
}

/* Fitting the pane (owner, 25 Oct 2026). Below FIT_BELOW px the table keeps
   Name, then the key columns that fit at KEY_MIN each beside NAME_MIN for the
   name, a 44 px chevron and the tick column while selecting. Widths include
   the cells' padding. A narrow row's Stage cell carries the next action under
   it; with no room for a column, both go under the name. */
const FIT_BELOW = 860;
const NAME_MIN = 132;
const KEY_MIN = 116;
// "tomorrow 12:00 AM" under a stage is 124 px at 12.5 px: 144 with the cell's padding.
const KEY_MAX = 144;
const TAP = 44;
/** Which columns earn a place in a narrow row first. */
const KEY_ORDER: Column[] = [
  "stage",
  "next",
  "owner",
  "last",
  "source",
  "contact",
  "age",
  "phone",
  "reason",
  "created",
  "pipeline",
];

/** The pane's width in CSS px, or 0 before it is known (a test, the server). */
function usePaneWidth(pane: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  // Measured before the first paint, so a phone never sees the wide table.
  useLayoutEffect(() => {
    const node = pane.current;
    if (!node) return;
    const read = () => setWidth(node.clientWidth);
    read();
    if (typeof ResizeObserver !== "function") return;
    const observer = new ResizeObserver(read);
    observer.observe(node);
    return () => observer.disconnect();
  }, [pane]);
  return width;
}

/** The narrow layout: the key columns in the row and each one's width. */
export function fitColumns<C extends string>(
  width: number,
  shown: readonly C[],
  order: readonly C[],
  ticks: boolean,
): { keys: C[]; keyWidth: number } | null {
  if (!width || width >= FIT_BELOW) return null;
  const room = width - NAME_MIN - TAP - (ticks ? TAP : 0);
  const ranked = order.filter((column) => shown.includes(column));
  const count = Math.max(
    0,
    Math.min(ranked.length, Math.floor(room / KEY_MIN)),
  );
  const keys = ranked.slice(0, count);
  return {
    keys: shown.filter((column) => keys.includes(column)),
    keyWidth: Math.max(
      KEY_MIN,
      Math.min(KEY_MAX, Math.floor(room / Math.max(1, keys.length))),
    ),
  };
}

/** How long a lead has sat in its stage, in words ("3 days"). */
export function inStage(
  row: Pick<LeadRow, "stage_at">,
  now = new Date(),
): string | null {
  return row.stage_at ? ago(row.stage_at, now).replace(" ago", "") : null;
}

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
    case "age":
      // Longest in its stage first when sorted down; unknown last.
      return row.stage_at
        ? -new Date(row.stage_at).getTime()
        : Number.MIN_SAFE_INTEGER;
    case "contact":
      return row.last_contact_at ? new Date(row.last_contact_at).getTime() : 0;
    case "reason":
      return (row.outcome_reason_label ?? "~").toLowerCase();
    case "created":
      return new Date(row.created_at).getTime();
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
  serverSort = null,
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
  /** Heads that sort the whole list on the server (name, next action, last
   *  contact, added); the other heads sort the rows loaded. */
  serverSort?: {
    by: ListSort | null;
    down: boolean;
    onSort: (sort: ListSort, order: "asc" | "desc") => void;
  } | null;
}) {
  const [sort, setSort] = useState<{ by: Column; down: boolean } | null>(null);
  const grid = useRef<HTMLTableElement>(null);
  const pane = useRef<HTMLDivElement | null>(null);
  const paneWidth = usePaneWidth(pane);
  // Narrow rows opened to show the columns that don't fit.
  const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set());
  // A stage that asks for something (a reason, a follow-up, the meeting).
  const [asking, setAsking] = useState<{
    lead: LeadRow;
    moves: MoveOption[];
    step: string;
  } | null>(null);
  const rights: EditRights | null = edit
    ? {
        ...edit,
        onNeeds: (row: LeadRow, step: string) =>
          void readLead(row.lead_id).then(
            (detail) =>
              setAsking({ lead: detail.lead, moves: detail.moves ?? [], step }),
            () => undefined,
          ),
      }
    : null;
  const edits = useLeadEdits(rows, selecting ? null : rights, pipelineNames);
  const [picking, setPicking] = useState(false);
  const [chosenColumns, setChosenColumns] =
    useState<ReadonlySet<Column> | null>(null);
  const visible =
    chosenColumns ??
    (typeof window === "undefined" ? SHOWN_AT_FIRST : readShown());
  const toggleColumn = (column: Column) => {
    const next = new Set(visible);
    if (next.has(column)) next.delete(column);
    else next.add(column);
    keepShown(next);
    setChosenColumns(next);
  };
  const columns: Column[] = [
    "name",
    ...(visible.has("phone") ? (["phone"] as const) : []),
    "stage",
    ...(pipelineNames ? (["pipeline"] as const) : []),
    ...(showOwner ? (["owner"] as const) : []),
    ...(
      ["source", "next", "last", "age", "contact", "reason", "created"] as const
    ).filter((column) => visible.has(column)),
  ];
  const fit = fitColumns(
    paneWidth,
    columns.filter((column) => column !== "name"),
    KEY_ORDER,
    selecting,
  );
  // In a narrow pane: Name and the key columns in the row, the rest under it.
  const rowColumns: Column[] = fit ? ["name", ...fit.keys] : columns;
  // The next action rides under the stage (or under the name, with no room
  // for a column) rather than waiting in the opened row.
  const nextWithStage =
    !!fit &&
    rowColumns.includes("stage") &&
    !rowColumns.includes("next") &&
    columns.includes("next");
  const statusUnderName = !!fit && fit.keys.length === 0;
  const underColumns: Column[] = fit
    ? columns.filter(
        (column) =>
          !rowColumns.includes(column) &&
          !(column === "next" && (nextWithStage || statusUnderName)) &&
          !(column === "stage" && statusUnderName),
      )
    : [];
  const toggleOpen = (leadId: string) =>
    setOpened((current) => {
      const next = new Set(current);
      if (next.has(leadId)) next.delete(leadId);
      else next.add(leadId);
      return next;
    });
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
    let index = rowColumns.indexOf(from as Column);
    const down =
      event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    const across =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    event.preventDefault();
    for (;;) {
      line += down;
      index += across;
      if (line < 0 || line >= shown.length) return;
      if (index < 0 || index >= rowColumns.length) return;
      const next = grid.current?.querySelector<HTMLElement>(
        `[data-cell="${cellKey(shown[line].lead_id, rowColumns[index])}"]`,
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
              {statusUnderName ? (
                <small>
                  {row.stage_label}
                  {columns.includes("next") && row.next_action_at ? (
                    <span data-late={row.overdue ? "" : undefined}>
                      {` · ${when(row.next_action_at, now)}`}
                    </span>
                  ) : null}
                </small>
              ) : row.company || row.city ? (
                <small>{row.company ?? row.city}</small>
              ) : null}
            </button>
            {/* A narrow row keeps its width for the name: rename on the lead page. */}
            {!fit && edits.can(row, "name") ? (
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
        return nextWithStage ? (
          <span className={styles.stageStack}>
            <span className={styles.stage}>{row.stage_label}</span>
            {row.next_action_at ? (
              <small data-late={row.overdue ? "" : undefined}>
                {when(row.next_action_at, now)}
              </small>
            ) : (
              <small className={styles.quiet}>No next step</small>
            )}
          </span>
        ) : (
          <span className={styles.stage}>{row.stage_label}</span>
        );
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
      case "age":
        return inStage(row, now) ?? <span className={styles.quiet}>–</span>;
      case "contact":
        return row.last_contact_at ? (
          ago(row.last_contact_at, now)
        ) : (
          <span className={styles.quiet}>Never</span>
        );
      case "reason":
        return (
          row.outcome_reason_label ?? <span className={styles.quiet}>–</span>
        );
      case "created":
        return when(row.created_at, now);
    }
  };

  const editing = (row: LeadRow, column: Column) =>
    EDIT_COLUMNS.has(column) &&
    edits.can(row, column as EditColumn) &&
    edits.editing?.leadId === row.lead_id &&
    edits.editing.column === column;

  /** A cell's inside: its editor, a quiet button that starts one, or text. */
  const body = (row: LeadRow, column: Column): ReactNode => {
    if (editing(row, column)) return editor(row, column as EditColumn);
    const editable =
      EDIT_COLUMNS.has(column) && edits.can(row, column as EditColumn);
    return editable && column !== "name" ? (
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
    );
  };

  const across = rowColumns.length + (selecting ? 1 : 0) + (fit ? 1 : 0);

  return (
    <div
      className={styles.wrap}
      data-fit={fit ? "" : undefined}
      ref={(node) => {
        pane.current = node;
        if (keysRef) keysRef.current = node;
      }}
    >
      <div className={styles.columnsBar}>
        {fit && underColumns.length ? (
          <small className={styles.columnsNote}>
            {underColumns.length === 1
              ? "1 more column under each row"
              : `${underColumns.length} more columns under each row`}
          </small>
        ) : null}
        <button
          type="button"
          className={styles.columnsButton}
          aria-expanded={picking}
          onClick={() => setPicking((open) => !open)}
        >
          <Columns3 size={16} aria-hidden="true" />
          Columns
        </button>
        {picking ? (
          <fieldset className={styles.columnsMenu}>
            <legend className={styles.srOnly}>Columns to show</legend>
            {fit ? (
              <p className={styles.columnsHint}>
                {`${rowColumns.map((column) => LABELS[column]).join(", ")} fit in each row. The rest open from the row's arrow.`}
              </p>
            ) : null}
            {OPTIONAL.map((column) => (
              <label key={column}>
                <input
                  type="checkbox"
                  checked={visible.has(column)}
                  onChange={() => toggleColumn(column)}
                />
                {LABELS[column]}
              </label>
            ))}
          </fieldset>
        ) : null}
      </div>
      {fit && quickAdd ? (
        <div className={styles.quickAbove}>
          <QuickAddBar
            pipeline={quickAdd.pipeline}
            onAdded={quickAdd.onAdded}
            onPasteRows={quickAdd.onPasteRows}
          />
        </div>
      ) : null}
      <table
        ref={grid}
        className={styles.table}
        aria-label="Leads"
        onKeyDown={onGridKey}
        style={
          fit
            ? ({ "--key-width": `${fit.keyWidth}px` } as CSSProperties)
            : undefined
        }
      >
        <thead>
          <tr>
            {selecting ? (
              <th scope="col" className={styles.pick}>
                <span className={styles.srOnly}>Select</span>
              </th>
            ) : null}
            {rowColumns.map((column) => {
              const server = serverSort ? SERVER_SORT[column] : undefined;
              const sorted = server
                ? serverSort?.by === server
                : sort?.by === column;
              const down = server ? !!serverSort?.down : !!sort?.down;
              return (
                <th
                  key={column}
                  scope="col"
                  data-column={column}
                  aria-sort={
                    sorted ? (down ? "descending" : "ascending") : "none"
                  }
                >
                  <button
                    type="button"
                    className={styles.sort}
                    onClick={() => {
                      if (server && serverSort) {
                        // The whole list, by the server: a second tap turns it round.
                        setSort(null);
                        serverSort.onSort(
                          server,
                          sorted ? (down ? "asc" : "desc") : "asc",
                        );
                        return;
                      }
                      setSort((current) =>
                        current?.by === column
                          ? current.down
                            ? null
                            : { by: column, down: true }
                          : { by: column, down: false },
                      );
                    }}
                  >
                    {column === "stage" && nextWithStage
                      ? "Stage · next"
                      : LABELS[column]}
                    {sorted ? (
                      down ? (
                        <ArrowDown size={13} aria-hidden="true" />
                      ) : (
                        <ArrowUp size={13} aria-hidden="true" />
                      )
                    ) : null}
                  </button>
                </th>
              );
            })}
            {fit ? (
              <th scope="col" className={styles.more}>
                <span className={styles.srOnly}>More</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => {
            const open = fit !== null && opened.has(row.lead_id);
            const name = displayName(row.name);
            return (
              <Fragment key={row.lead_id}>
                <tr
                  data-selected={chosen?.has(row.lead_id) ? "" : undefined}
                  data-open={open ? "" : undefined}
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
                        aria-label={`Select ${name}`}
                      />
                    </td>
                  ) : null}
                  {rowColumns.map((column) =>
                    editing(row, column) ? (
                      <td
                        key={column}
                        data-column={column}
                        data-editing=""
                        onClick={(event) => event.stopPropagation()}
                      >
                        {body(row, column)}
                      </td>
                    ) : (
                      <td key={column} data-column={column}>
                        {body(row, column)}
                      </td>
                    ),
                  )}
                  {fit ? (
                    <td className={styles.more}>
                      {underColumns.length ? (
                        <button
                          type="button"
                          className={styles.moreButton}
                          aria-expanded={open}
                          aria-controls={`more-${row.lead_id}`}
                          aria-label={`${open ? "Hide" : "Show"} more about ${name}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            toggleOpen(row.lead_id);
                          }}
                        >
                          <ChevronDown size={18} aria-hidden="true" />
                        </button>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
                {open ? (
                  <tr id={`more-${row.lead_id}`} className={styles.moreRow}>
                    <td colSpan={across}>
                      <dl className={styles.moreList}>
                        {underColumns.map((column) => (
                          <div
                            key={column}
                            data-column={column}
                            data-editing={editing(row, column) ? "" : undefined}
                          >
                            <dt>{LABELS[column]}</dt>
                            <dd>{body(row, column)}</dd>
                          </div>
                        ))}
                      </dl>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
        {quickAdd && !fit ? (
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
      {asking ? (
        <StageSheet
          open
          lead={asking.lead}
          moves={asking.moves}
          initial={asking.step}
          via="table"
          onClose={() => setAsking(null)}
          onMoved={() => {
            setAsking(null);
            edit?.onSaved();
          }}
        />
      ) : null}
    </div>
  );
}
