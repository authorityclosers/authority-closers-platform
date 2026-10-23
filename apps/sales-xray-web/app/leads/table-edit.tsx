"use client";

/**
 * Editing in the Leads table (owner P0, 23 Oct 2026: "a Notion-like table ...
 * inline editing with Tab/Enter flow"). A lead's owner, or an owner or admin,
 * clicks a cell to change it: the name and number are typed; the stage, and for
 * owners and admins the owner and pipeline, are picked. Enter saves and goes down
 * the column, Tab along the row, Escape leaves the cell as it was, and clicking
 * away saves. Each save carries the lead's revision and waits for that lead's
 * previous save, so quick edits never trip over each other; a lead someone else
 * changed meanwhile says so in a corner card and the list reads again.
 */

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { readJourney } from "./journey/journey-client";
import {
  LeadsError,
  editLead,
  movePipeline,
  moveToStage,
  readLead,
  readTeam,
  reassign,
  type LeadDetail,
  type LeadRow,
  type Stage,
} from "./leads-client";
import styles from "./leads-table.module.css";

export type EditColumn = "name" | "phone" | "stage" | "owner" | "pipeline";
/** Where the next edit goes once this one is saved. */
export type Move = "down" | "next" | "back" | null;
export type Choice = { value: string; label: string; kind?: Stage };

export type EditRights = {
  /** Owners and admins: every lead, and its owner and pipeline too. */
  canManage: boolean;
  /** The viewer: a seller changes their own leads. */
  me: string | null;
  /** Saved: the list and its counts read again, once editing stops. */
  onSaved: () => void;
};

export const EDIT_COLUMNS: ReadonlySet<string> = new Set([
  "name",
  "phone",
  "stage",
  "owner",
  "pipeline",
]);

/** Saves this long apart read the list once. */
const SETTLE_MS = 1200;

const MAIN = "main";

function save(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  column: EditColumn,
  value: string,
): Promise<LeadDetail> {
  switch (column) {
    case "name":
      return editLead(lead, { name: value });
    case "phone":
      return editLead(lead, { phone: value });
    case "stage":
      return moveToStage(lead, value);
    case "owner":
      return reassign(lead, value || null);
    case "pipeline":
      return movePipeline(lead, value);
  }
}

export function useLeadEdits(
  rows: LeadRow[],
  rights: EditRights | null,
  pipelineNames: ReadonlyMap<string, string> | null,
) {
  const [editing, setEditing] = useState<{
    leadId: string;
    column: EditColumn;
    /** Started by a click: a pick list opens its choices at once. */
    open: boolean;
  } | null>(null);
  // What the server said after each save, until the list reads it too.
  const [saved, setSaved] = useState<ReadonlyMap<string, LeadRow>>(
    () => new Map(),
  );
  // What was just typed or picked, shown while it saves.
  const [pending, setPending] = useState<ReadonlyMap<string, Partial<LeadRow>>>(
    () => new Map(),
  );
  const [stages, setStages] = useState<ReadonlyMap<string, Choice[]>>(
    () => new Map(),
  );
  const [team, setTeam] = useState<Choice[] | null>(null);
  const asked = useRef(new Set<string>());
  const queue = useRef(new Map<string, Promise<void>>());
  const revisions = useRef(new Map<string, number>());
  const settle = useRef<number | undefined>(undefined);
  const latest = useRef({ rights, editing });
  useEffect(() => {
    latest.current = { rights, editing };
  });
  useEffect(() => () => window.clearTimeout(settle.current), []);

  const shown = useMemo(
    () =>
      rows.map((row) => {
        const known = saved.get(row.lead_id);
        const base = known && known.revision > row.revision ? known : row;
        const typed = pending.get(row.lead_id);
        return typed ? { ...base, ...typed } : base;
      }),
    [rows, saved, pending],
  );

  const can = (row: LeadRow, column: EditColumn) => {
    if (!rights) return false;
    if (column === "owner" || column === "pipeline") return rights.canManage;
    return (
      rights.canManage ||
      (rights.me !== null && row.owner_person_id === rights.me)
    );
  };

  const loadStages = (pipeline: string) => {
    if (asked.current.has(`stages:${pipeline}`)) return;
    asked.current.add(`stages:${pipeline}`);
    readJourney(pipeline).then(
      (view) =>
        setStages((current) =>
          new Map(current).set(
            pipeline,
            // A call says when nobody picked up; nobody picks that by hand.
            view.stages
              .filter(
                (stage) => !stage.archived && stage.kind !== "not_connected",
              )
              .map((stage) => ({
                value: stage.key,
                label: stage.label,
                kind: stage.kind,
              })),
          ),
        ),
      () => setStages((current) => new Map(current).set(pipeline, [])),
    );
  };

  const loadTeam = () => {
    if (asked.current.has("team")) return;
    asked.current.add("team");
    readTeam().then(
      (view) =>
        setTeam(
          view.reps
            .map((rep) => ({
              value: rep.person_id,
              label: displayName(rep.name),
            }))
            .sort((a, b) => a.label.localeCompare(b.label)),
        ),
      () => setTeam([]),
    );
  };

  const current = (row: LeadRow, column: EditColumn): string => {
    switch (column) {
      case "name":
        return row.name;
      case "phone":
        return "";
      case "stage":
        return (
          row.step ??
          stages
            .get(row.pipeline ?? MAIN)
            ?.find((choice) => choice.kind === row.stage)?.value ??
          ""
        );
      case "owner":
        return row.owner_person_id ?? "";
      case "pipeline":
        return row.pipeline ?? MAIN;
    }
  };

  /** A pick list's choices (null while they load), the lead's own first if missing. */
  const choices = (row: LeadRow, column: EditColumn): Choice[] | null => {
    const now = current(row, column);
    const withNow = (list: Choice[], label: string) =>
      now && !list.some((choice) => choice.value === now)
        ? [{ value: now, label }, ...list]
        : list;
    switch (column) {
      case "stage": {
        const list = stages.get(row.pipeline ?? MAIN);
        return list ? withNow(list, row.stage_label) : null;
      }
      case "owner":
        return team
          ? [
              { value: "", label: "No owner" },
              ...withNow(team, displayName(row.owner_name ?? "")),
            ]
          : null;
      case "pipeline":
        return withNow(
          [...(pipelineNames ?? new Map<string, string>())].map(
            ([value, label]) => ({ value, label }),
          ),
          row.pipeline ?? MAIN,
        );
      default:
        return null;
    }
  };

  const start = (row: LeadRow, column: EditColumn, open = false) => {
    if (!can(row, column)) return;
    if (column === "stage") loadStages(row.pipeline ?? MAIN);
    if (column === "owner") loadTeam();
    setEditing({ leadId: row.lead_id, column, open });
  };

  const stop = () => setEditing(null);

  /** The list reads again once saves pause and nobody is mid-edit. */
  const readSoon = () => {
    window.clearTimeout(settle.current);
    settle.current = window.setTimeout(() => {
      if (latest.current.editing) readSoon();
      else latest.current.rights?.onSaved();
    }, SETTLE_MS);
  };

  const commit = (row: LeadRow, column: EditColumn, typed: string) => {
    const value =
      column === "name" || column === "phone" ? typed.trim() : typed;
    if (value === current(row, column)) return;
    // A lead keeps its name and number: emptied, they stay as they were.
    if ((column === "name" || column === "phone") && !value) return;
    const choice = choices(row, column)?.find((item) => item.value === value);
    const patch: Partial<LeadRow> =
      column === "name"
        ? { name: value }
        : column === "phone"
          ? { phone_last4: value.replace(/\D/g, "").slice(-4) || null }
          : column === "stage"
            ? {
                step: value,
                stage_label: choice?.label ?? row.stage_label,
                ...(choice?.kind ? { stage: choice.kind } : {}),
              }
            : column === "owner"
              ? {
                  owner_person_id: value || null,
                  owner_name: value ? (choice?.label ?? null) : null,
                }
              : { pipeline: value };
    const id = row.lead_id;
    setPending((now) => new Map(now).set(id, { ...now.get(id), ...patch }));
    const run = (queue.current.get(id) ?? Promise.resolve())
      .then(async () => {
        const detail = await save(
          {
            lead_id: id,
            revision: Math.max(row.revision, revisions.current.get(id) ?? 0),
          },
          column,
          value,
        );
        revisions.current.set(id, detail.lead.revision);
        setSaved((now) => new Map(now).set(id, detail.lead));
      })
      .catch((reason: unknown) => {
        const changed = reason instanceof LeadsError && reason.status === 409;
        notify({
          id: "lead-edit",
          tone: "error",
          title: changed ? "This lead changed" : "That change wasn't saved",
          message:
            reason instanceof LeadsError
              ? reason.message
              : "Check your connection and try again.",
        });
        if (changed) latest.current.rights?.onSaved();
      })
      .finally(() => {
        setPending((now) => {
          const left = { ...now.get(id) };
          for (const key of Object.keys(patch))
            delete left[key as keyof LeadRow];
          const next = new Map(now);
          if (Object.keys(left).length) next.set(id, left);
          else next.delete(id);
          return next;
        });
        if (queue.current.get(id) === run) queue.current.delete(id);
        readSoon();
      });
    queue.current.set(id, run);
  };

  return { shown, editing, can, start, stop, commit, current, choices };
}

type Done = (value: string | null, move: Move, refocus: boolean) => void;

const keyMove = (event: KeyboardEvent): Move | undefined =>
  event.key === "Enter"
    ? "down"
    : event.key === "Tab"
      ? event.shiftKey
        ? "back"
        : "next"
      : undefined;

/** A typed cell: the name, or the number (read from the lead, as only its last
    four digits are listed). Returns null when nothing changed. */
export function TextEditor({
  initial,
  phoneOf,
  label,
  onDone,
}: {
  initial: string;
  /** The lead whose whole number fills the box once read. */
  phoneOf?: string;
  label: string;
  onDone: Done;
}) {
  const [draft, setDraft] = useState(initial);
  const start = useRef(initial);
  const touched = useRef(false);
  const finished = useRef(false);
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    box.current?.focus();
  }, []);
  useEffect(() => {
    if (!phoneOf) return;
    const controller = new AbortController();
    readLead(phoneOf, controller.signal).then(
      (detail) => {
        if (touched.current || !detail.phone) return;
        start.current = detail.phone;
        setDraft(detail.phone);
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [phoneOf]);
  const finish = (value: string | null, move: Move, refocus: boolean) => {
    if (finished.current) return;
    finished.current = true;
    onDone(
      value !== null && value.trim() !== start.current.trim() ? value : null,
      move,
      refocus,
    );
  };
  return (
    <input
      ref={box}
      className={styles.cellInput}
      value={draft}
      onChange={(event) => {
        touched.current = true;
        setDraft(event.target.value);
      }}
      onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return;
        const move = keyMove(event);
        if (move) {
          event.preventDefault();
          finish(draft, move, true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          finish(null, null, true);
        }
      }}
      onBlur={() => finish(draft, null, false)}
      aria-label={label}
      autoComplete="off"
      {...(phoneOf
        ? { type: "tel", inputMode: "tel" as const, maxLength: 40 }
        : { maxLength: 200 })}
    />
  );
}

/** A picked cell: the stage, owner or pipeline. A click's pick saves at once;
    arrow keys only choose, and Enter or Tab saves. Returns null when unchanged. */
export function PickEditor({
  value,
  options,
  open,
  label,
  onDone,
}: {
  value: string;
  /** Null while the choices load. */
  options: Choice[] | null;
  /** Opened by a click: show the choices straight away. */
  open: boolean;
  label: string;
  onDone: Done;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const keyed = useRef(false);
  const finished = useRef(false);
  const box = useRef<HTMLSelectElement>(null);
  const ready = options !== null;
  useEffect(() => {
    box.current?.focus();
  }, []);
  useEffect(() => {
    if (!open || !ready) return;
    try {
      (box.current as { showPicker?: () => void } | null)?.showPicker?.();
    } catch {
      // No picker without a fresh tap (or in this browser): the box is focused.
    }
  }, [open, ready]);
  const chosen = draft ?? value;
  const finish = (next: string | null, move: Move, refocus: boolean) => {
    if (finished.current) return;
    finished.current = true;
    onDone(next !== null && next !== value ? next : null, move, refocus);
  };
  return (
    <select
      ref={box}
      className={styles.cellInput}
      value={ready ? chosen : ""}
      onChange={(event) => {
        setDraft(event.target.value);
        if (!keyed.current) finish(event.target.value, null, true);
      }}
      onKeyDown={(event) => {
        const move = keyMove(event);
        if (move) {
          event.preventDefault();
          finish(chosen, move, true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          finish(null, null, true);
        } else keyed.current = true;
      }}
      onBlur={() => finish(chosen, null, false)}
      aria-label={label}
    >
      {ready ? (
        options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))
      ) : (
        <option value="">Loading…</option>
      )}
    </select>
  );
}
