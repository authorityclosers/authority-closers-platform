"use client";

/**
 * Managing many leads (owner, 16 Nov 2026: "selecting leads, managing the
 * leads, the UI is terrible, very hard to manage leads, even table and all";
 * picks 17 Nov: M2-A laptop table "I require that anyhow", M1-A phone dock,
 * M1-B phone top bar "amazing, love it", M1-C assign with seller load
 * "perfect, needed"). Lead-management study 02 §4-§5.
 *
 * One selection, scoped to the list on screen: ticked leads by id, or "all N
 * matching", which sends the list's own filter for the server to freeze
 * (POST /leads/bulk-jobs, up to 2,000, with the count the screen showed so a
 * list that changed is refused rather than acted on). Every change shows an
 * Undo for 10 seconds; the server keeps it undoable for 30 minutes.
 *
 * - Laptop: the bar replaces the list's toolbar ("25 selected · Assign ·
 *   Change stage · Add tag · Archive · More · Clear"), with the scope banner
 *   under it.
 * - Phone: a top bar (✕, "3 selected", Select all) and the scope banner, and a
 *   dock of four (Assign, Stage, Tag, More) where the Call band was. No red
 *   button in the dock: Archive and the Bin live in More.
 *
 * Archive and Move to Bin show (SHELF_ACTIONS_ENABLED) now that Leads has its
 * Archived and Bin lists with Restore (M3-A, /leads/shelf); v1.78 hid them
 * while the 10-second Undo was the only way back (PR 637 review).
 */

import {
  Archive,
  ChevronDown,
  Layers,
  MessageCircle,
  MoreHorizontal,
  Tag,
  Trash2,
  UserRoundPlus,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { notify } from "../notice-center";
import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  BULK_JOB_LIMIT,
  commandId,
  LeadsError,
  readSellerLoads,
  runBulkJob,
  undoBulkJob,
  type BulkJob,
  type BulkJobRequest,
  type LeadFilter,
  type ListMore,
  type SellerLoads,
} from "./leads-client";
import styles from "./manage-bar.module.css";

/** What a bulk change acts on: ticked leads, or every lead the list matches. */
export type Selection =
  | { kind: "ids"; ids: string[] }
  | { kind: "filter"; filter: LeadFilter; total: number };

export const selectionCount = (selection: Selection) =>
  selection.kind === "ids" ? selection.ids.length : selection.total;

/** The selection as the bulk-jobs request names it. */
export function selectionRequest(
  selection: Selection,
): Pick<BulkJobRequest, "lead_ids" | "filter" | "expected_total"> {
  return selection.kind === "ids"
    ? { lead_ids: selection.ids }
    : { filter: selection.filter, expected_total: selection.total };
}

/** The list's question (GET /leads) as a bulk job's frozen filter. */
export function filterOf(ask: {
  scope: "mine" | "team" | "unassigned";
  owner?: string;
  stage?: string | null;
  search?: string;
  test?: boolean;
  pipeline?: string | null;
  more?: ListMore | null;
}): LeadFilter {
  const more = ask.more ?? {};
  const filter: LeadFilter = { scope: ask.scope };
  const put = <K extends keyof LeadFilter>(key: K, value: unknown) => {
    if (value !== null && value !== undefined && value !== "")
      filter[key] = value as LeadFilter[K];
  };
  put("side", more.side);
  put("view", more.view);
  put("step", more.step);
  put("when", more.when);
  put("source", more.source);
  put("due", more.due);
  put("contact", more.contact);
  put("created", more.created);
  put("since", more.since);
  put("until", more.until);
  put("owner", ask.owner);
  put("pipeline", ask.pipeline);
  put("stage", ask.stage);
  put("search", ask.search?.trim().slice(0, 80));
  if (ask.test) filter.test = true;
  return filter;
}

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count.toLocaleString("en-IN")} ${count === 1 ? one : many}`;

export const leadsWord = (count: number) => plural(count, "lead");

/* ---------- Where the selection shows ---------- */

// The laptop bar from 900 px, where the Call band stops being fixed
// (work-views.module.css); below it, the phone's top bar and dock.
const DESK = "(min-width: 900px)";
const watchDesk = (change: () => void) => {
  const query = window.matchMedia?.(DESK);
  query?.addEventListener?.("change", change);
  return () => query?.removeEventListener?.("change", change);
};

export function useDeskSelect(): boolean {
  return useSyncExternalStore(
    watchDesk,
    () => window.matchMedia?.(DESK).matches ?? true,
    () => true,
  );
}

// The table's own width (leads-table.tsx): from here a computer opens Leads
// as the table (pick M2-A, 17 Nov 2026) unless the person chose the list.
const WIDE = "(min-width: 1100px)";
const watchWide = (change: () => void) => {
  const query = window.matchMedia?.(WIDE);
  query?.addEventListener?.("change", change);
  return () => query?.removeEventListener?.("change", change);
};

export function useWideList(): boolean {
  return useSyncExternalStore(
    watchWide,
    () => window.matchMedia?.(WIDE).matches ?? false,
    () => false,
  );
}

/* ---------- Seller load, read once a selection starts ---------- */

// The team and their loads are asked for when ticking starts, so the Assign
// sheet never opens on "Loading your team…" (study 02 §3b: 250 ms p95).
const loadsRead = new Map<string, { at: number; read: Promise<SellerLoads> }>();
const LOADS_FRESH_MS = 30_000;

export function readLoadsSoon(side: "inbound" | "cold"): Promise<SellerLoads> {
  const kept = loadsRead.get(side);
  if (kept && Date.now() - kept.at < LOADS_FRESH_MS) return kept.read;
  const read = readSellerLoads(side);
  loadsRead.set(side, { at: Date.now(), read });
  read.catch(() => loadsRead.delete(side));
  return read;
}

/** After a change, the next sheet reads the loads again. */
export function forgetLoads() {
  loadsRead.clear();
}

/* ---------- Running a change, with Undo ---------- */

export function failWords(reason: unknown, fallback: string): string {
  return reason instanceof LeadsError ? reason.message : fallback;
}

/** One bulk change; its answer shows with Undo for 10 seconds. */
export async function runWithUndo(
  change: BulkJobRequest,
  command = commandId(),
): Promise<BulkJob> {
  const job = await runBulkJob(change, command);
  forgetLoads();
  const failed = job.failed.reduce((sum, item) => sum + item.count, 0);
  notify({
    id: "bulk-job",
    tone: job.changed ? "success" : "info",
    title: job.words,
    message: failed
      ? `${plural(failed, "lead")} couldn't change: ${job.failed
          .map((item) => item.reason)
          .join(", ")}.`
      : undefined,
    timeout: 10_000,
    action:
      job.undoable && job.changed
        ? {
            label: "Undo",
            icon: "none",
            run: () => {
              void undoBulkJob(job.job_id).then(
                (undone) => {
                  forgetLoads();
                  notify({
                    id: "bulk-job",
                    tone: "success",
                    title: undone.skipped
                      ? `${plural(undone.restored, "lead")} put back · ${plural(undone.skipped, "lead")} changed since, left as they are`
                      : `${plural(undone.restored, "lead")} put back`,
                    timeout: 6000,
                  });
                  window.dispatchEvent(new Event(UNDONE_EVENT));
                },
                (reason: unknown) =>
                  notify({
                    id: "bulk-job",
                    tone: "error",
                    title: "Couldn't undo that",
                    message: failWords(reason, "Try again in a moment."),
                  }),
              );
            },
          }
        : undefined,
  });
  return job;
}

/** A bulk change was undone: the list reads again. */
export const UNDONE_EVENT = "sx-leads-bulk-undone";

/**
 * Tags on leads: not built yet (the lead-management API, 17 Nov 2026: "leads
 * have no tags yet, so bulk tag is not built"). The dock keeps its place for
 * it and says so, rather than doing nothing.
 */
export type TagChange = {
  selection: Selection;
  tags: string[];
  mode: "add" | "remove" | "replace";
};
export function tagLeads(change: TagChange): Promise<BulkJob> {
  void change;
  return Promise.reject(
    new LeadsError("Tags come in a later update: leads have no tags yet.", 501),
  );
}

/** Archive and Move to Bin in the bars: on, as the Archived and Bin lists with
 * Restore are reachable from the Leads menu (M3-A; off in v1.78, PR 637). */
export const SHELF_ACTIONS_ENABLED = true;

/** The bars' actions with Archive and the Bin taken off while
 * SHELF_ACTIONS_ENABLED is false. */
export function withShelf(
  actions: ManageActions,
  enabled: boolean = SHELF_ACTIONS_ENABLED,
): ManageActions {
  return enabled
    ? actions
    : { ...actions, onArchive: undefined, onBin: undefined };
}

export function sayTagsLater() {
  notify({
    id: "bulk-tag",
    tone: "info",
    title: "Tags are coming",
    message: SHELF_ACTIONS_ENABLED
      ? "Leads have no tags yet. Assign, Stage and Archive work now."
      : "Leads have no tags yet. Assign and Stage work now.",
    timeout: 5000,
  });
}

/* ---------- The scope banner ---------- */

export function ScopeBanner({
  count,
  loaded,
  total,
  allMatching,
  where,
  onAllMatching,
  onClear,
}: {
  /** Ticked now (all matching: the total). */
  count: number;
  /** Rows on screen. */
  loaded: number;
  /** Leads in this list on the server. */
  total: number;
  allMatching: boolean;
  /** The list's own words ("To Call"). */
  where: string;
  onAllMatching: () => void;
  onClear: () => void;
}) {
  if (allMatching)
    return (
      <p className={styles.banner} role="status">
        {`All ${total.toLocaleString("en-IN")} in ${where} are selected.`}{" "}
        <button type="button" className={styles.bannerLink} onClick={onClear}>
          Clear
        </button>
      </p>
    );
  if (!count || count < loaded) return null;
  if (total <= loaded)
    return (
      <p className={styles.banner} role="status">
        {`All ${total.toLocaleString("en-IN")} in ${where} are selected.`}
      </p>
    );
  if (total > BULK_JOB_LIMIT)
    return (
      <p className={styles.banner} role="status">
        {`All ${count.toLocaleString("en-IN")} on screen are selected. ${total.toLocaleString("en-IN")} match: up to 2,000 change at a time, so narrow the list first.`}
      </p>
    );
  return (
    <p className={styles.banner} role="status">
      {`All ${count.toLocaleString("en-IN")} on screen are selected.`}{" "}
      <button
        type="button"
        className={styles.bannerLink}
        onClick={onAllMatching}
      >
        {`Select all ${total.toLocaleString("en-IN")} in ${where}`}
      </button>
    </p>
  );
}

/* ---------- More: a small menu ---------- */

type MoreItem = {
  key: string;
  label: string;
  icon: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  run: () => void;
};

function MoreMenu({
  items,
  trigger,
  up,
}: {
  items: MoreItem[];
  trigger: (open: boolean, toggle: () => void) => ReactNode;
  /** Opens upwards (the phone's dock). */
  up?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", key, true);
    };
  }, [open]);
  return (
    <span className={styles.moreBox} ref={box}>
      {trigger(open, () => setOpen((value) => !value))}
      {open ? (
        <span className={styles.menu} role="menu" data-up={up ? "" : undefined}>
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              className={styles.menuItem}
              data-danger={item.danger ? "" : undefined}
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.run();
              }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </span>
      ) : null}
    </span>
  );
}

export type ManageActions = {
  onAssign: () => void;
  onStage: () => void;
  onTag: () => void;
  /** Archive (hidden while SHELF_ACTIONS_ENABLED is false). */
  onArchive?: () => void;
  /** Send a WhatsApp template (ticked leads only). */
  onWhatsApp?: () => void;
  /** Move to the Bin (owners and admins). */
  onBin?: () => void;
};

function moreItems(actions: ManageActions, withArchive: boolean): MoreItem[] {
  const items: MoreItem[] = [];
  if (withArchive && actions.onArchive)
    items.push({
      key: "archive",
      label: "Archive",
      icon: <Archive size={18} aria-hidden="true" />,
      run: actions.onArchive,
    });
  items.push({
    key: "whatsapp",
    label: "Send a WhatsApp template",
    icon: <MessageCircle size={18} aria-hidden="true" />,
    disabled: !actions.onWhatsApp,
    run: () => actions.onWhatsApp?.(),
  });
  if (actions.onBin)
    items.push({
      key: "bin",
      label: "Move to Bin…",
      icon: <Trash2 size={18} aria-hidden="true" />,
      danger: true,
      run: actions.onBin,
    });
  return items;
}

/* ---------- Laptop: the bar in place of the toolbar ---------- */

export function TableBulkBar({
  count,
  busy,
  actions,
  onClear,
  banner,
}: {
  count: number;
  busy: boolean;
  actions: ManageActions;
  onClear: () => void;
  banner: ReactNode;
}) {
  const off = !count || busy;
  return (
    <div className={styles.deskWrap} data-select-bar="">
      <div
        className={styles.deskBar}
        role="toolbar"
        aria-label="Selected leads"
      >
        <span className={styles.deskCount} aria-live="polite">
          {count
            ? `${count.toLocaleString("en-IN")} selected`
            : "Tick leads to change them"}
        </span>
        <span className={styles.deskRule} aria-hidden="true" />
        <button
          type="button"
          className={styles.deskAction}
          disabled={off}
          onClick={actions.onAssign}
        >
          <UserRoundPlus size={18} aria-hidden="true" />
          Assign
        </button>
        <button
          type="button"
          className={styles.deskAction}
          disabled={off}
          onClick={actions.onStage}
        >
          <Layers size={18} aria-hidden="true" />
          Change stage
        </button>
        <button
          type="button"
          className={styles.deskAction}
          disabled={off}
          onClick={actions.onTag}
        >
          <Tag size={18} aria-hidden="true" />
          Add tag
        </button>
        {actions.onArchive ? (
          <button
            type="button"
            className={styles.deskAction}
            disabled={off}
            onClick={actions.onArchive}
          >
            <Archive size={18} aria-hidden="true" />
            Archive
          </button>
        ) : null}
        <MoreMenu
          items={moreItems(actions, false)}
          trigger={(open, toggle) => (
            <button
              type="button"
              className={styles.deskAction}
              disabled={off}
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={toggle}
            >
              More
              <ChevronDown size={16} aria-hidden="true" />
            </button>
          )}
        />
        <span className={styles.deskEnd}>
          <span className={styles.deskRule} aria-hidden="true" />
          <button type="button" className={styles.deskClear} onClick={onClear}>
            Clear
          </button>
        </span>
      </div>
      {banner}
    </div>
  );
}

/* ---------- Phone: the top bar and the dock ---------- */

export function PhoneSelectTop({
  count,
  busy,
  allOnScreen,
  onClose,
  onSelectAll,
  banner,
}: {
  count: number;
  busy: boolean;
  /** Every lead on screen is ticked: Select all has nothing more to tick. */
  allOnScreen: boolean;
  onClose: () => void;
  onSelectAll: () => void;
  banner: ReactNode;
}) {
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className={styles.phoneTop} data-select-bar="">
      <div
        className={styles.phoneBar}
        role="toolbar"
        aria-label="Selected leads"
      >
        <button
          type="button"
          className={styles.phoneClose}
          aria-label="Stop selecting"
          onClick={onClose}
        >
          <X size={24} aria-hidden="true" />
        </button>
        <span className={styles.phoneCount} aria-live="polite">
          {`${count.toLocaleString("en-IN")} selected`}
        </span>
        {allOnScreen ? null : (
          <button
            type="button"
            className={styles.phoneAll}
            disabled={busy}
            onClick={onSelectAll}
          >
            Select all
          </button>
        )}
      </div>
      {banner}
    </div>,
    document.body,
  );
}

export function PhoneDock({
  count,
  busy,
  actions,
}: {
  count: number;
  busy: boolean;
  actions: ManageActions;
}) {
  const off = !count || busy;
  const item = (label: string, icon: ReactNode, run: () => void) => (
    <button
      type="button"
      className={styles.dockAction}
      disabled={off}
      onClick={run}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
  return (
    <div
      className={styles.dock}
      role="toolbar"
      aria-label="Change the selected leads"
      data-select-bar=""
    >
      {item(
        "Assign",
        <UserRoundPlus size={24} aria-hidden="true" />,
        actions.onAssign,
      )}
      {item("Stage", <Layers size={24} aria-hidden="true" />, actions.onStage)}
      {item("Tag", <Tag size={24} aria-hidden="true" />, actions.onTag)}
      <MoreMenu
        up
        items={moreItems(actions, true)}
        trigger={(open, toggle) => (
          <button
            type="button"
            className={styles.dockAction}
            disabled={off}
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={toggle}
          >
            <MoreHorizontal size={24} aria-hidden="true" />
            <span>More</span>
          </button>
        )}
      />
    </div>
  );
}

/* ---------- Archive and Bin: one confirm each ---------- */

export function ShelfSheet({
  open,
  action,
  selection,
  onClose,
  onDone,
}: {
  open: boolean;
  action: "archive" | "bin";
  selection: Selection;
  onClose: () => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  // One command per confirm: a retry never acts twice.
  const [command] = useState(commandId);
  const count = selectionCount(selection);
  const leads = leadsWord(count);
  const archive = action === "archive";
  const go = async () => {
    setBusy(true);
    try {
      await runWithUndo({ ...selectionRequest(selection), action }, command);
      onDone();
    } catch (reason) {
      notify({
        id: "bulk-job",
        tone: "error",
        title: archive
          ? "Those leads weren't archived"
          : "Those leads weren't moved",
        message: failWords(reason, "Check your connection and try again."),
      });
      setBusy(false);
    }
  };
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={archive ? `Archive ${leads}?` : `Move ${leads} to the Bin?`}
      wide="center"
      footer={
        <span className={styles.sheetActions}>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          {archive ? (
            <Button onClick={() => void go()} disabled={busy}>
              {busy ? "Archiving…" : `Archive ${leads}`}
            </Button>
          ) : (
            <button
              type="button"
              className={styles.binButton}
              onClick={() => void go()}
              disabled={busy}
            >
              {busy ? "Moving…" : "Move to Bin"}
            </button>
          )}
        </span>
      }
    >
      <p className={styles.sheetText}>
        {archive
          ? "They leave your lists and counts. History, notes and messages are kept. Bring them back any time from Archived."
          : "You can restore them for 30 days. After that they're deleted for good."}
      </p>
    </Sheet>
  );
}
