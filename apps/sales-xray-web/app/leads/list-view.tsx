"use client";

/**
 * Leads in one stage (owner, 22 Oct 2026: stage tabs instead of the
 * Everyone / Mine / No owner bar). The page owns the stage, whose leads and
 * the search; this draws the list for them, says how many, offers Select to
 * owners and admins, and hands the stage counts up for the tabs.
 */

import {
  List,
  ListChecks,
  X,
  SearchX,
  Table2,
  UserPlus,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { notify } from "../notice-center";
import { useRowKeys } from "../ui/row-keys";
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
import { BulkSheet } from "./bulk-sheet";
import { LeadsTable } from "./leads-table";
import { QuickAddBar, type PasteRows } from "./quick-add";
import styles from "./leads.module.css";

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

export function ListView({
  canManage,
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
  pipeline = null,
  tools = null,
  filtered = false,
  onClearFilters,
  onAdd,
  onShowOpen,
  layoutOwner,
  pipelineNames = null,
  me = null,
  onPasteRows,
  more: refine = null,
  onSort,
}: {
  canManage: boolean;
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
  if (layout.owner !== layoutOwner)
    setLayout({ owner: layoutOwner, value: storedLayout(layoutOwner) });
  const asTable = layout.value === "table";
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
    stage === "open" || stage === "new"
      ? { pipeline, onAdded: () => onChanged?.(), onPasteRows }
      : null;
  const [loaded, setLoaded] = useState<{
    key: string;
    question: string;
    page: LeadPage;
    rows: LeadRow[];
  } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(
    null,
  );
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
    scope,
    owner,
    stage,
    query,
    pipeline,
    moreKey,
  ]);
  const key = JSON.stringify([
    scope,
    owner,
    stage,
    query,
    pipeline,
    moreKey,
    version,
  ]);
  const ownerCounts = useRef(onOwnerCounts);
  useEffect(() => {
    ownerCounts.current = onOwnerCounts;
  });
  const page = loaded?.question === question ? loaded.page : null;
  const rows = loaded?.question === question ? loaded.rows : [];
  const error = failed?.key === key ? failed.message : null;
  const chosen = picked?.question === question ? picked.leads : NONE;
  // The page's latest counts setter, without reading the list again for it.
  const counts = useRef(onCounts);
  useEffect(() => {
    counts.current = onCounts;
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
  useRowKeys(
    tableKeys,
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
    !selecting && asTable,
  );
  const ask = {
    scope,
    owner: owner ?? undefined,
    stage: stage === TEST ? null : stage,
    search: query,
    test: stage === TEST,
    pipeline,
    more: refine,
  };

  useEffect(() => {
    const controller = new AbortController();
    readLeads(
      {
        scope,
        owner: owner ?? undefined,
        stage: stage === TEST ? null : stage,
        search: query,
        test: stage === TEST,
        pipeline,
        // The filters as one string: the same filters never ask twice.
        more: JSON.parse(moreKey) as ListMore | null,
      },
      controller.signal,
    )
      .then((next) => {
        setLoaded({ key, question, page: next, rows: next.leads });
        if (next.stage_counts && stage !== TEST)
          counts.current?.(next.stage_counts);
        const owners = (
          next as typeof next & { owner_counts?: Record<string, number> }
        ).owner_counts;
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
  }, [key, question, scope, owner, stage, query, pipeline, moreKey]);

  const more = async () => {
    if (!page?.next_offset || loadingMore) return;
    setLoadingMore(true);
    try {
      const next = await readLeads({ ...ask, offset: page.next_offset });
      setLoaded((current) =>
        current?.key === key
          ? {
              key,
              question,
              page: next,
              rows: [...current.rows, ...next.leads],
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
  const hasMore = page?.next_offset != null;
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
        const read = { key, question, page: last, rows: all };
        setLoaded((current) => (current?.key === key ? read : current));
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
      <section className={styles.listPanel} aria-label={stageLabel}>
        <div className={styles.listHead}>
          <span className={styles.listTotal} aria-live="polite">
            {page
              ? `${page.total} ${page.total === 1 ? "lead" : "leads"}`
              : null}
          </span>
          <span className={styles.listTools}>
            {selecting ? null : tools}
            {/* The table's Columns sit here, beside the layout they belong to. */}
            {asTable && !selecting ? (
              <span className={styles.columnsSlot} ref={setColumnsSlot} />
            ) : null}
            {rows.length && !selecting ? (
              // One switch with both choices in words (owner, 25 Oct 2026:
              // "Done next to Table" read as one control).
              <span
                className={styles.layoutSwitch}
                role="group"
                aria-label="Show leads as"
              >
                <button
                  type="button"
                  aria-pressed={!asTable}
                  title="Show as a list"
                  onClick={() => chooseLayout("list")}
                >
                  <List size={14} aria-hidden="true" />
                  List
                </button>
                <button
                  type="button"
                  aria-pressed={asTable}
                  title="Show as a table"
                  onClick={() => chooseLayout("table")}
                >
                  <Table2 size={14} aria-hidden="true" />
                  Table
                </button>
              </span>
            ) : null}
            {canManage && rows.length ? (
              <button
                type="button"
                className={styles.statusChip}
                aria-pressed={selecting}
                onClick={() => {
                  setPicked(null);
                  setSelecting((value) => !value);
                }}
              >
                {selecting ? (
                  <>
                    <X size={14} aria-hidden="true" />
                    Cancel
                  </>
                ) : (
                  <>
                    <ListChecks size={14} aria-hidden="true" />
                    Select
                  </>
                )}
              </button>
            ) : null}
          </span>
        </div>
        {quickAdd &&
        page !== null &&
        !selecting &&
        !(asTable && rows.length) ? (
          <QuickAddBar
            pipeline={quickAdd.pipeline}
            onAdded={quickAdd.onAdded}
            onPasteRows={quickAdd.onPasteRows}
          />
        ) : null}
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : page === null ? (
          <div
            className={styles.listSkeleton}
            aria-busy="true"
            aria-label="Loading leads"
          >
            {[0, 1, 2, 3, 4].map((key) => (
              <Skeleton key={key} height={52} />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyList
            stage={stage}
            stageLabel={stageLabel}
            query={query}
            filtered={filtered || !!query}
            onClearFilters={onClearFilters}
            onAdd={onAdd}
            onShowOpen={onShowOpen}
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
                chosen={chosen}
                onToggle={toggle}
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
                {rows.map((row) =>
                  selecting ? (
                    <SelectLine
                      key={row.lead_id}
                      row={row}
                      selected={chosen.has(row.lead_id)}
                      onToggle={toggle}
                    />
                  ) : (
                    <LeadLine
                      key={row.lead_id}
                      row={row}
                      onOpen={onOpen}
                      showOwner={scope !== "mine"}
                      actions={actions}
                    />
                  ),
                )}
              </ul>
            )}
            {page.next_offset !== null ? (
              <div className={styles.more} ref={end}>
                <Button onClick={more} disabled={loadingMore}>
                  {loadingMore
                    ? "Loading…"
                    : `Show more (${rows.length} of ${page.total})`}
                </Button>
              </div>
            ) : null}
          </>
        )}
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
  query,
  filtered,
  onClearFilters,
  onAdd,
  onShowOpen,
}: {
  stage: string;
  stageLabel: string;
  query: string;
  filtered: boolean;
  onClearFilters?: () => void;
  onAdd?: () => void;
  onShowOpen?: () => void;
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
          query
            ? "Try another name, city or the last digits of a number."
            : "Nobody here for whose leads you picked."
        }
        action={action("Clear filters", onClearFilters)}
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
