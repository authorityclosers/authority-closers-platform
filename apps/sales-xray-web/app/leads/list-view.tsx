"use client";

/**
 * Leads in one stage (owner, 22 Oct 2026: stage tabs instead of the
 * Everyone / Mine / No owner bar). The page owns the stage, whose leads and
 * the search; this draws the list for them, says how many, offers Select to
 * owners and admins, and hands the stage counts up for the tabs.
 */

import dynamic from "next/dynamic";
import {
  CloudOff,
  List,
  ListChecks,
  X,
  SearchX,
  Table2,
  UserPlus,
  Users,
} from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { inStageList, inWorkView, useLeadMoves, withMoves } from "./lead-moves";
import { OPENING_STAGE } from "./opening";
import { cachedLeadPage, readFirstLeads } from "./list-cache";
import { firstPageFor, type ServerLeads } from "./leads-seed";
import { notify } from "../notice-center";
import { useRowKeys } from "../ui/row-keys";
import { withoutRepeats } from "./page-merge";
import { useListLoadWatch } from "./load-watch";
import { Button, Skeleton } from "../ui/kit";
import {
  DeleteLeadsSheet,
  SelectBar,
  SelectLine,
  type Doomed,
} from "./delete-leads";
import { InlineEmpty, LeadLine, type RowActions } from "./desk-view";
import {
  DELETE_LIMIT,
  LeadsError,
  readLeads,
  type LeadPage,
  type LeadRow,
  type LeadsDeleted,
  type ListMore,
  type ListSort,
} from "./leads-client";
import { QuickAddBar, type PasteRows } from "./quick-add";
import styles from "./leads.module.css";

const CachedLeadLine = memo(LeadLine);
const subscribeHydration = () => () => {};

const BulkSheet = dynamic(
  () => import("./bulk-sheet").then((module) => module.BulkSheet),
  { ssr: false },
);

const LeadsTable = dynamic(
  () => import("./leads-table").then((m) => m.LeadsTable),
  { ssr: false },
);

export type Scope = "mine" | "team" | "unassigned";

/** Test and sample leads in every stage, easy to clear (owners and admins). */
export const TEST = "test";
const NONE: ReadonlyMap<string, string> = new Map();

/** List or Table, remembered per person and workspace on this device. */
type Layout = "list" | "table";
const layoutKey = (owner: string) => `sx:leads-layout:${owner}`;
function storedLayout(owner: string | undefined): Layout {
  if (!owner || typeof window === "undefined") return "list";
  try {
    return window.localStorage.getItem(layoutKey(owner)) === "table"
      ? "table"
      : "list";
  } catch {
    return "list";
  }
}

/** The stage the server is asked for: none for test leads and for the work
 *  views' list (its view and stage pick are in `more`). */
const askedStage = (stage: string) =>
  stage === TEST || stage === OPENING_STAGE ? null : stage;

export function ListView({
  canManage,
  initial = null,
  cacheIdentity,
  stage,
  stageLabel,
  scope,
  owner = null,
  onOwnerCounts,
  query,
  onOpen,
  version,
  actions,
  onChanged,
  onCounts,
  onTable,
  onStepCounts,
  pipeline = null,
  tools = null,
  filtered = false,
  onClearFilters,
  onAdd,
  onShowOpen,
  onSearchAll,
  layoutOwner,
  pipelineNames = null,
  me = null,
  onPasteRows,
  more: refine = null,
  onSort,
  onTopLead,
  onOrder,
  stageWord,
  quietLate = false,
  heading = null,
  empty = null,
}: {
  canManage: boolean;
  /** A lead's stage, named for the side shown (compact rows). */
  stageWord?: (row: LeadRow) => string | undefined;
  /** Rows never turn red: Cold Leads for a seller (owner, 31 Oct 2026). */
  quietLate?: boolean;
  /** The list's own line ("Inbound leads to call"), its count beside it. */
  heading?: string | null;
  /** What an empty list says, when the page knows better than its stage. */
  empty?: { title: string; text: string } | null;
  /** The list's first lead, or null: Start calling opens it. */
  onTopLead?: (leadId: string | null) => void;
  /** The leads in the list's order, as shown: Call Next goes through them. */
  onOrder?: (leadIds: readonly string[]) => void;
  initial?: ServerLeads | null;
  cacheIdentity?: string | null;
  /** "open", a stage kind, or "test". */
  stage: string;
  /** The tab's own words, for the count and the empty list. */
  stageLabel: string;
  scope: Scope;
  /** One seller's leads (team scope, owners and admins): the seller chips. */
  owner?: string | null;
  /** Leads per seller for these filters, when the server counts them. */
  onOwnerCounts?: (counts: Record<string, number>) => void;
  /** Search words, already settled (the page waits for typing to stop). */
  query: string;
  onOpen: (leadId: string) => void;
  version: number;
  actions?: RowActions;
  /** Leads were deleted: the desk's counts read again. */
  onChanged?: () => void;
  /** Every stage's count for this scope and search, for the tabs. */
  onCounts?: (counts: Record<string, number>) => void;
  /** Whether the rows show as the table: the page gives it the whole width. */
  onTable?: (table: boolean) => void;
  /** Each of the owner's stages' count, for the Pipeline stage picker. */
  onStepCounts?: (counts: Record<string, number>) => void;
  /** One pipeline's leads; none: every pipeline's. */
  pipeline?: string | null;
  /** Beside Select on the list's head: the saved views. */
  tools?: ReactNode;
  /** A search or whose-leads pick narrows the list (an empty list can clear it). */
  filtered?: boolean;
  onClearFilters?: () => void;
  /** An empty Open list offers Add lead; another stage, the open leads. */
  onAdd?: () => void;
  onShowOpen?: () => void;
  /** A search that found nothing in this view runs over All Leads. */
  onSearchAll?: () => void;
  /** Who chose List or Table (person and workspace), for remembering it. */
  layoutOwner?: string;
  /** Several pipelines: each one's name, for the table's Pipeline column. */
  pipelineNames?: ReadonlyMap<string, string> | null;
  /** The viewer: the table lets a seller change their own leads in place. */
  me?: string | null;
  /** Rows pasted into quick add go to the import. */
  onPasteRows?: PasteRows;
  /** Sort and filters over the whole list, answered by the server. */
  more?: ListMore | null;
  /** A table head tapped: sort the whole list by it. */
  onSort?: (sort: ListSort, order: "asc" | "desc") => void;
}) {
  // Table on phones and computers alike (owner, 24 Oct 2026: "we can't actually
  // access table view ... on mobile"); the choice is remembered per person.
  const [layout, setLayout] = useState(() => ({
    owner: layoutOwner,
    value: storedLayout(layoutOwner),
  }));
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    () => true,
    () => false,
  );
  if (layout.owner !== layoutOwner)
    setLayout({ owner: layoutOwner, value: storedLayout(layoutOwner) });
  const asTable = hydrated && layout.value === "table";
  // The page gives a table the whole width until a lead opens (owner, 31 Oct 2026).
  const tableTold = useRef(onTable);
  useLayoutEffect(() => {
    tableTold.current = onTable;
  });
  useEffect(() => {
    tableTold.current?.(asTable);
  }, [asTable]);
  const chooseLayout = (value: Layout) => {
    setLayout({ owner: layoutOwner, value });
    if (!layoutOwner) return;
    try {
      window.localStorage.setItem(layoutKey(layoutOwner), value);
    } catch {
      // Storage blocked: the choice lasts for this visit.
    }
  };
  const tableKeys = useRef<HTMLDivElement>(null);
  // Quick add where a new lead lands: All leads and New (owner P0, 23 Oct 2026).
  const quickAdd =
    stage === "open" || stage === "new" || stage === OPENING_STAGE
      ? { pipeline, onAdded: () => onChanged?.(), onPasteRows }
      : null;
  // Counts and sync update the parent callbacks. Keep unchanged rows reusable,
  // while their next tap always uses the handlers from the latest commit.
  const handlers = useRef({ onOpen, actions });
  useLayoutEffect(() => {
    handlers.current = { onOpen, actions };
  });
  const openRow = useCallback((id: string) => handlers.current.onOpen(id), []);
  const call = !!actions?.onCall;
  const log = !!actions?.onLog;
  const message = !!actions?.onMessage;
  const hold = !!actions?.onHold;
  const tap = !!actions?.onTap;
  const rowActions = useMemo<RowActions>(
    () => ({
      onCall: call
        ? (row) => handlers.current.actions?.onCall?.(row)
        : undefined,
      onLog: log ? (row) => handlers.current.actions?.onLog?.(row) : undefined,
      onMessage: message
        ? (row) => handlers.current.actions?.onMessage?.(row)
        : undefined,
      onHold: hold
        ? (row) => handlers.current.actions?.onHold?.(row)
        : undefined,
      onTap: tap
        ? (row, channel) => handlers.current.actions?.onTap?.(row, channel)
        : undefined,
    }),
    [call, log, message, hold, tap],
  );
  const [loaded, setLoaded] = useState<{
    key: string;
    question: string;
    page: LeadPage;
    rows: LeadRow[];
    /** When the rows were asked for. */
    at?: number;
  } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(
    null,
  );
  // "Try again" on a read that failed: the same question, asked once more.
  const [attempt, setAttempt] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  // Select (owners and admins): tick leads, then Delete. What is ticked belongs
  // to the question it was ticked in; another filter starts with none.
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<{
    question: string;
    leads: ReadonlyMap<string, string>;
  } | null>(null);
  const [loadingAll, setLoadingAll] = useState(false);
  // Actions on the ticked leads: a fresh sheet each time.
  const [columnsSlot, setColumnsSlot] = useState<HTMLElement | null>(null);
  const [bulk, setBulk] = useState<{
    round: number;
    open: boolean;
    step?: "assign" | "stage";
  } | null>(null);
  const [confirm, setConfirm] = useState<{
    round: number;
    open: boolean;
    leads: Doomed[];
  } | null>(null);
  // Results remember the question they answer; until the current one is
  // answered the list shows its skeleton. A refresh of the same question
  // (pull down, back in the app) keeps the rows on screen meanwhile.
  const moreKey = JSON.stringify(refine ?? null);
  const question = JSON.stringify([
    layoutOwner,
    cacheIdentity,
    scope,
    owner,
    stage,
    query,
    pipeline,
    moreKey,
  ]);
  const key = JSON.stringify([
    layoutOwner,
    cacheIdentity,
    scope,
    owner,
    stage,
    query,
    pipeline,
    moreKey,
    version,
    attempt,
  ]);
  const ownerCounts = useRef(onOwnerCounts);
  useEffect(() => {
    ownerCounts.current = onOwnerCounts;
  });
  const remembered = useMemo(
    () =>
      cachedLeadPage(cacheIdentity, {
        scope,
        owner: owner ?? undefined,
        stage: askedStage(stage),
        search: query,
        test: stage === TEST,
        pipeline,
        more: JSON.parse(moreKey) as ListMore | null,
      }),
    [cacheIdentity, scope, owner, stage, query, pipeline, moreKey],
  );
  const [initialRead] = useState(initial);
  const serverPage = firstPageFor(initialRead, cacheIdentity, {
    scope,
    stage,
    query,
    pipeline,
    owner,
    more: refine,
  });
  const page =
    loaded?.question === question ? loaded.page : (serverPage ?? remembered);
  const read = useMemo(
    () => (loaded?.question === question ? loaded.rows : (page?.leads ?? [])),
    [loaded, question, page],
  );
  // The person's moves at once: a lead moved to another stage leaves this
  // list, and joins the top of its new stage's (owner, 30 Oct 2026).
  const moves = useLeadMoves();
  const readAt = loaded?.question === question ? (loaded.at ?? 0) : 0;
  const join = !filtered && !query.trim() && !owner && scope !== "unassigned";
  const rows = useMemo(
    () =>
      withMoves(read, moves, {
        belongs:
          stage === TEST
            ? null
            : (row) => inStageList(row, stage) && inWorkView(row, refine),
        join,
        readAt,
      }),
    [read, moves, stage, join, readAt, refine],
  );
  // ...and the next lead is on top: no scrolling for the next call.
  const panel = useRef<HTMLElement>(null);
  const seenMoves = useRef(moves);
  useEffect(() => {
    if (seenMoves.current === moves) return;
    seenMoves.current = moves;
    const shown = new Set(rows.map((row) => row.lead_id));
    const left = read.some((row) => !shown.has(row.lead_id));
    const top = panel.current?.getBoundingClientRect().top;
    if (left && top !== undefined && top < 0)
      panel.current?.scrollIntoView({ block: "start" });
  }, [moves, read, rows]);
  // Start calling opens this tab's first lead (owner and Dipak, 30 Oct 2026).
  const topLead = useRef(onTopLead);
  useEffect(() => {
    topLead.current = onTopLead;
  });
  const top = rows[0]?.lead_id ?? null;
  useEffect(() => {
    topLead.current?.(top);
  }, [top]);
  const orderTo = useRef(onOrder);
  useEffect(() => {
    orderTo.current = onOrder;
  });
  const order = rows.map((row) => row.lead_id).join(" ");
  useEffect(() => {
    orderTo.current?.(order ? order.split(" ") : []);
  }, [order]);
  // Paint the visible phone rows first. Building 50 gesture-enabled rows at
  // once monopolises a mid-range phone even when the data is already cached.
  const [revealed, setRevealed] = useState({ question: "", count: 8 });
  const visibleCount = revealed.question === question ? revealed.count : 8;
  useEffect(() => {
    if (asTable || visibleCount >= rows.length) return;
    const timer = window.setTimeout(
      () =>
        setRevealed({
          question,
          count: Math.min(rows.length, visibleCount + 16),
        }),
      80,
    );
    return () => window.clearTimeout(timer);
  }, [question, rows.length, visibleCount, asTable]);
  const syncing = loaded?.key !== key;
  const error = failed?.key === key ? failed.message : null;
  useListLoadWatch({
    question: key,
    waiting: syncing,
    failed: error !== null,
    showing: page !== null,
    onRetry: () => setAttempt((count) => count + 1),
  });
  const chosen = picked?.question === question ? picked.leads : NONE;
  // The page's latest counts setter, without reading the list again for it.
  const counts = useRef(onCounts);
  const stepCounts = useRef(onStepCounts);
  useEffect(() => {
    counts.current = onCounts;
    stepCounts.current = onStepCounts;
  });
  // Keys on a computer: J/K, Enter, C (asks before calling), L. Not while ticking.
  const list = useRef<HTMLUListElement>(null);
  const byId = (id: string) => rows.find((row) => row.lead_id === id);
  useRowKeys(
    list,
    {
      open: onOpen,
      call: (id) => {
        const row = byId(id);
        if (row?.phone_last4) actions?.onCall?.(row);
      },
      log: (id) => {
        const row = byId(id);
        if (row) actions?.onLog?.(row);
      },
    },
    !selecting && !asTable,
  );
  const ask = {
    scope,
    owner: owner ?? undefined,
    stage: askedStage(stage),
    search: query,
    test: stage === TEST,
    pipeline,
    more: refine,
  };

  const loadedWindow = useRef({ question, count: rows.length });
  useEffect(() => {
    loadedWindow.current = { question, count: rows.length };
  }, [question, rows.length]);
  useEffect(() => {
    const controller = new AbortController();
    const asked = Date.now();
    const parameters = {
      scope,
      owner: owner ?? undefined,
      stage: askedStage(stage),
      search: query,
      test: stage === TEST,
      pipeline,
      more: JSON.parse(moreKey) as ListMore | null,
    };
    const keep =
      loadedWindow.current.question === question
        ? loadedWindow.current.count
        : 0;
    readFirstLeads(cacheIdentity, parameters, controller.signal)
      .then(async (first) => {
        if (controller.signal.aborted) return;
        // A minute refresh must not throw away the pages already scrolled.
        // Keep them usable while the same loaded window is revalidated.
        let next = first;
        let fresh = withoutRepeats([], first.leads);
        while (
          fresh.length < Math.min(keep, first.total) &&
          next.next_offset !== null
        ) {
          next = await readLeads(
            { ...parameters, offset: next.next_offset },
            controller.signal,
          );
          if (controller.signal.aborted) return;
          fresh = withoutRepeats(fresh, next.leads);
        }
        setLoaded({ key, question, page: next, rows: fresh, at: asked });
        if (first.stage_counts && stage !== TEST)
          counts.current?.(first.stage_counts);
        if (first.step_counts && stage !== TEST)
          stepCounts.current?.(first.step_counts);
        const owners = first.owner_counts;
        if (owners && Object.keys(owners).length) ownerCounts.current?.(owners);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setFailed({
          key,
          message:
            reason instanceof LeadsError
              ? reason.message
              : "Leads didn't load.",
        });
      });
    return () => controller.abort();
  }, [
    key,
    question,
    scope,
    owner,
    stage,
    query,
    pipeline,
    moreKey,
    cacheIdentity,
    remembered,
  ]);

  const more = async () => {
    if (!page?.next_offset || loadingMore || syncing) return;
    setLoadingMore(true);
    try {
      const next = await readLeads({ ...ask, offset: page.next_offset });
      setLoaded((current) =>
        current?.key === key
          ? {
              key,
              question,
              page: next,
              rows: withoutRepeats(current.rows, next.leads),
              at: current.at,
            }
          : current,
      );
    } catch (reason) {
      setFailed({
        key,
        message:
          reason instanceof LeadsError
            ? reason.message
            : "More leads didn't load.",
      });
    } finally {
      setLoadingMore(false);
    }
  };

  // The next page loads by itself when the list's end comes into view; the
  // button stays for keyboards and when scrolling can't be watched.
  const end = useRef<HTMLDivElement>(null);
  const loadMore = useRef(more);
  useEffect(() => {
    loadMore.current = more;
  });
  const hasMore =
    page?.next_offset != null &&
    !syncing &&
    (asTable || visibleCount >= rows.length);
  useEffect(() => {
    const target = end.current;
    if (!hasMore || !target || typeof IntersectionObserver === "undefined")
      return;
    const seen = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting))
          void loadMore.current();
      },
      { rootMargin: "600px 0px" },
    );
    seen.observe(target);
    return () => seen.disconnect();
  }, [hasMore, key]);

  // From the latest ticks, so quick taps in a row each count.
  const toggle = (row: LeadRow) =>
    setPicked((current) => {
      const next = new Map(
        current?.question === question ? current.leads : NONE,
      );
      if (next.has(row.lead_id)) next.delete(row.lead_id);
      else if (next.size < DELETE_LIMIT) next.set(row.lead_id, row.name);
      return { question, leads: next };
    });
  // Owner, 31 Oct 2026 (bug report 130): a long press on a phone, or the tick
  // beside a row on a computer, starts picking leads for the bulk bar.
  // Sellers keep the long press's quick actions.
  const pickFrom = useRef<(row: LeadRow) => void>(() => undefined);
  // The finger lifting after a long press lands on the row it just picked:
  // that tap doesn't untick it.
  const pickedBy = useRef<{ id: string; at: number } | null>(null);
  useLayoutEffect(() => {
    pickFrom.current = (row) => {
      pickedBy.current = { id: row.lead_id, at: Date.now() };
      setSelecting(true);
      toggle(row);
    };
  });
  const tapToggle = (row: LeadRow) => {
    const held = pickedBy.current;
    if (held && held.id === row.lead_id && Date.now() - held.at < 700) return;
    toggle(row);
  };
  const startPicking = useCallback((row: LeadRow) => pickFrom.current(row), []);
  const ownerActions = useMemo<RowActions>(
    () => ({ ...rowActions, onHold: startPicking }),
    [rowActions, startPicking],
  );
  const picksHere = canManage && stage === OPENING_STAGE;
  // The table's keys: J/K or arrows, Enter opens the lead beside it, C, L, and
  // Space ticks for an owner (also while leads are picked).
  useRowKeys(
    tableKeys,
    {
      open: onOpen,
      // Space ticks the focused row for an owner; the bar follows.
      tick: canManage
        ? (id) => {
            const row = byId(id);
            if (row) startPicking(row);
          }
        : undefined,
      call: (id) => {
        const row = byId(id);
        if (row?.phone_last4) actions?.onCall?.(row);
      },
      log: (id) => {
        const row = byId(id);
        if (row) actions?.onLog?.(row);
      },
    },
    asTable,
  );

  // Select all: the rest of the list is read first (up to the delete limit).
  const selectAll = async () => {
    if (!page || loadingAll) return;
    let all = rows;
    let last = page;
    if (last.next_offset !== null && all.length < DELETE_LIMIT) {
      setLoadingAll(true);
      try {
        while (last.next_offset !== null && all.length < DELETE_LIMIT) {
          last = await readLeads({ ...ask, offset: last.next_offset });
          all = [...all, ...last.leads];
        }
        setLoaded((current) =>
          current?.key === key
            ? { key, question, page: last, rows: all, at: current.at }
            : current,
        );
      } catch (reason) {
        notify({
          id: "lead-select",
          tone: "error",
          title: "Not every lead loaded",
          message:
            reason instanceof LeadsError
              ? reason.message
              : "Try Select all again.",
        });
        return;
      } finally {
        setLoadingAll(false);
      }
    }
    setPicked({
      question,
      leads: new Map(
        all.slice(0, DELETE_LIMIT).map((row) => [row.lead_id, row.name]),
      ),
    });
  };

  const deleted = (result: LeadsDeleted) => {
    const gone = new Set(result.lead_ids);
    setLoaded((current) =>
      current
        ? {
            ...current,
            page: {
              ...current.page,
              total: Math.max(0, current.page.total - result.deleted),
            },
            rows: current.rows.filter((row) => !gone.has(row.lead_id)),
          }
        : current,
    );
    setPicked(null);
    setSelecting(false);
    setConfirm((current) => current && { ...current, open: false });
    onChanged?.();
  };

  return (
    <>
      <section ref={panel} className={styles.listPanel} aria-label={stageLabel}>
        {heading ? <h2 className={styles.listHeading}>{heading}</h2> : null}
        <div className={styles.listHead}>
          <span className={styles.listTotal} aria-live="polite">
            {page
              ? `${page.total} ${stage === TEST ? "test " : ""}${page.total === 1 ? "lead" : "leads"}`
              : null}
          </span>
          {/* Only when it says something (owner, #73): "Updated just now"
              on every list was noise. */}
          <span
            className={styles.syncChip}
            aria-label="Lead sync"
            role="status"
            aria-live="polite"
            data-quiet={error || syncing ? undefined : ""}
          >
            {error ? "Sync paused" : syncing ? "Syncing…" : ""}
          </span>
          <span className={styles.listTools}>
            {selecting ? null : tools}
            {rows.length && !selecting ? (
              // List and Table as two small icons (owner, 31 Oct 2026), each named
              // on hover and to screen readers.
              <span
                className={styles.layoutSwitch}
                role="group"
                aria-label="Show leads as"
              >
                <button
                  type="button"
                  aria-pressed={!asTable}
                  title="Show as a list"
                  aria-label="List"
                  onClick={() => chooseLayout("list")}
                >
                  <List size={16} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-pressed={asTable}
                  title="Show as a table"
                  aria-label="Table"
                  onClick={() => chooseLayout("table")}
                >
                  <Table2 size={16} aria-hidden="true" />
                </button>
              </span>
            ) : null}
            {canManage && (selecting || stage === TEST) ? (
              <button
                type="button"
                className={`${styles.statusChip} ${styles.selectToggle}`}
                aria-label={selecting ? "Cancel" : "Select"}
                title={selecting ? "Cancel selection" : "Select leads"}
                aria-pressed={selecting}
                onClick={() => {
                  setPicked(null);
                  setSelecting((value) => !value);
                }}
              >
                {selecting ? (
                  <>
                    <X size={14} aria-hidden="true" />
                    <span className={styles.controlLabel}>Cancel</span>
                  </>
                ) : (
                  <>
                    <ListChecks size={14} aria-hidden="true" />
                    <span className={styles.controlLabel}>Select</span>
                  </>
                )}
              </button>
            ) : null}
          </span>
        </div>
        {!selecting && asTable ? (
          <div className={styles.listAux}>
            <span className={styles.columnsSlot} ref={setColumnsSlot} />
          </div>
        ) : null}
        {error && !page ? (
          // Calm, with a way on (report #27, 26 Oct 2026): nothing is lost.
          <InlineEmpty
            icon={CloudOff}
            title={error}
            text="Your leads are safe. Try again in a moment."
            action={
              <Button
                onClick={() => setAttempt((count) => count + 1)}
                className={styles.inlineEmptyAction}
              >
                Try again
              </Button>
            }
          />
        ) : page === null ? (
          <div
            className={styles.listSkeleton}
            role="status"
            aria-busy="true"
            aria-label="Loading leads"
          >
            {[0, 1, 2, 3, 4].map((key) => (
              <div
                key={key}
                className={styles.listLoadingRow}
                aria-hidden="true"
              >
                <Skeleton width={36} height={36} radius="circle" />
                <div className={styles.listLoadingText}>
                  <Skeleton width={144} height={16} />
                  <Skeleton width={112} height={12} />
                  <span className={styles.listLoadingActions}>
                    <Skeleton width={136} height={36} radius="pill" />
                  </span>
                </div>
                <Skeleton width={48} height={20} radius="pill" />
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyList
            stage={stage}
            stageLabel={stageLabel}
            empty={empty}
            query={query}
            filtered={filtered || !!query}
            onClearFilters={onClearFilters}
            onAdd={onAdd}
            onShowOpen={onShowOpen}
            onSearchAll={onSearchAll}
          />
        ) : (
          <>
            {asTable ? (
              <LeadsTable
                rows={rows}
                onOpen={onOpen}
                showOwner={scope !== "mine"}
                pipelineNames={pipeline ? null : pipelineNames}
                selecting={selecting}
                ticks={canManage}
                chosen={chosen}
                onToggle={startPicking}
                keysRef={tableKeys}
                columnsSlot={columnsSlot}
                quickAdd={selecting ? null : quickAdd}
                serverSort={
                  onSort
                    ? {
                        by: refine?.sort ?? null,
                        down: refine?.order === "desc",
                        onSort,
                      }
                    : null
                }
                edit={{
                  canManage,
                  me,
                  onSaved: () => onChanged?.(),
                }}
              />
            ) : (
              <ul className={styles.leadList} aria-label="Leads" ref={list}>
                {rows.slice(0, visibleCount).map((row) =>
                  selecting ? (
                    <SelectLine
                      key={row.lead_id}
                      row={row}
                      selected={chosen.has(row.lead_id)}
                      onToggle={tapToggle}
                    />
                  ) : (
                    <CachedLeadLine
                      key={row.lead_id}
                      row={row}
                      onOpen={openRow}
                      // The owner's name only on someone else's lead.
                      showOwner={scope !== "mine" && row.owner_person_id !== me}
                      actions={
                        actions
                          ? picksHere
                            ? ownerActions
                            : rowActions
                          : undefined
                      }
                      onPick={picksHere ? startPicking : undefined}
                      compact={stage === OPENING_STAGE}
                      stageWord={stageWord?.(row)}
                      quietLate={quietLate}
                    />
                  ),
                )}
              </ul>
            )}
            {page.next_offset !== null &&
            (asTable || visibleCount >= rows.length) ? (
              <div className={styles.more} ref={end}>
                <Button onClick={more} disabled={loadingMore || syncing}>
                  {syncing
                    ? "Syncing…"
                    : loadingMore
                      ? "Loading…"
                      : `Show more (${rows.length} of ${page.total})`}
                </Button>
              </div>
            ) : null}
          </>
        )}
        {quickAdd &&
        page !== null &&
        rows.length > 0 &&
        !selecting &&
        !(asTable && rows.length) ? (
          <div className={styles.quickAddAfter}>
            <QuickAddBar
              pipeline={quickAdd.pipeline}
              onAdded={quickAdd.onAdded}
              onPasteRows={quickAdd.onPasteRows}
            />
          </div>
        ) : null}
      </section>
      {selecting && page && rows.length ? (
        <SelectBar
          count={chosen.size}
          total={page.total}
          loaded={rows.length}
          busy={loadingAll}
          onAll={() => void selectAll()}
          onClear={() => setPicked(null)}
          onDelete={() =>
            setConfirm((current) => ({
              round: (current?.round ?? 0) + 1,
              open: true,
              leads: [...chosen].map(([lead_id, name]) => ({ lead_id, name })),
            }))
          }
          onActions={() =>
            setBulk((current) => ({
              round: (current?.round ?? 0) + 1,
              open: true,
            }))
          }
          onAssign={() =>
            setBulk((current) => ({
              round: (current?.round ?? 0) + 1,
              open: true,
              step: "assign",
            }))
          }
          onMove={() =>
            setBulk((current) => ({
              round: (current?.round ?? 0) + 1,
              open: true,
              step: "stage",
            }))
          }
        />
      ) : null}
      {bulk ? (
        <BulkSheet
          key={bulk.round}
          open={bulk.open}
          leadIds={[...chosen.keys()]}
          pipeline={pipeline}
          initialStep={bulk.step ?? "menu"}
          onClose={() =>
            setBulk((current) => current && { ...current, open: false })
          }
          onDone={() => {
            setBulk((current) => current && { ...current, open: false });
            setPicked(null);
            setSelecting(false);
            onChanged?.();
          }}
        />
      ) : null}
      {confirm ? (
        <DeleteLeadsSheet
          key={confirm.round}
          open={confirm.open}
          leads={confirm.leads}
          onClose={() =>
            setConfirm((current) => current && { ...current, open: false })
          }
          onDeleted={deleted}
        />
      ) : null}
    </>
  );
}

/**
 * An empty list says what goes here and offers one way on (ease-of-use wave #9,
 * 22 Oct 2026): a narrowed list clears its filters, an empty Open list adds a lead,
 * any other stage goes back to the open leads.
 */
function EmptyList({
  stage,
  stageLabel,
  empty,
  query,
  filtered,
  onClearFilters,
  onAdd,
  onShowOpen,
  onSearchAll,
}: {
  stage: string;
  stageLabel: string;
  empty?: { title: string; text: string } | null;
  query: string;
  filtered: boolean;
  onClearFilters?: () => void;
  onAdd?: () => void;
  onShowOpen?: () => void;
  onSearchAll?: () => void;
}) {
  const action = (label: string, run?: () => void) =>
    run ? (
      <Button onClick={run} className={styles.inlineEmptyAction}>
        {label}
      </Button>
    ) : null;
  if (filtered)
    return (
      <InlineEmpty
        icon={SearchX}
        title="No leads match"
        text={
          query && onSearchAll
            ? "Not in this list. It may be in All Leads."
            : query
              ? "Try another name, city or the last digits of a number."
              : "Nobody here for whose leads you picked."
        }
        action={
          query && onSearchAll
            ? action("Search All Leads", onSearchAll)
            : action("Clear filters", onClearFilters)
        }
      />
    );
  if (stage === TEST)
    return (
      <InlineEmpty
        icon={Users}
        title="No test leads"
        text="Test and sample leads show here, ready to clear."
        action={action("See open leads", onShowOpen)}
      />
    );
  if (empty)
    return (
      <InlineEmpty
        icon={Users}
        title={empty.title}
        text={empty.text}
        action={stage === OPENING_STAGE ? action("Add lead", onAdd) : null}
      />
    );
  if (stage === "open")
    return (
      <InlineEmpty
        icon={UserPlus}
        title="No leads yet"
        text="Add your first lead, or connect your ad form in Lead sources."
        action={action("Add lead", onAdd)}
      />
    );
  return (
    <InlineEmpty
      icon={Users}
      title={`No leads in ${stageLabel}`}
      text="A lead moves here from its own page, after a call."
      action={action("See open leads", onShowOpen)}
    />
  );
}
