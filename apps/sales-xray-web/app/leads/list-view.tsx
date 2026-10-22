"use client";

/**
 * Leads in one stage (owner, 22 Oct 2026: stage tabs instead of the
 * Everyone / Mine / No owner bar). The page owns the stage, whose leads and
 * the search; this draws the list for them, says how many, offers Select to
 * owners and admins, and hands the stage counts up for the tabs.
 */

import { ListChecks, SearchX, Users } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { notify } from "../notice-center";
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
} from "./leads-client";
import { BulkSheet } from "./bulk-sheet";
import styles from "./leads.module.css";

export type Scope = "mine" | "team" | "unassigned";

/** Test and sample leads in every stage, easy to clear (owners and admins). */
export const TEST = "test";
const NONE: ReadonlyMap<string, string> = new Map();

export function ListView({
  canManage,
  stage,
  stageLabel,
  scope,
  query,
  onOpen,
  version,
  actions,
  onChanged,
  onCounts,
  pipeline = null,
  tools = null,
}: {
  canManage: boolean;
  /** "open", a stage kind, or "test". */
  stage: string;
  /** The tab's own words, for the count and the empty list. */
  stageLabel: string;
  scope: Scope;
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
}) {
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
  const [bulk, setBulk] = useState<{ round: number; open: boolean } | null>(
    null,
  );
  const [confirm, setConfirm] = useState<{
    round: number;
    open: boolean;
    leads: Doomed[];
  } | null>(null);
  // Results remember the question they answer; until the current one is
  // answered the list shows its skeleton. A refresh of the same question
  // (pull down, back in the app) keeps the rows on screen meanwhile.
  const question = JSON.stringify([scope, stage, query, pipeline]);
  const key = JSON.stringify([scope, stage, query, pipeline, version]);
  const page = loaded?.question === question ? loaded.page : null;
  const rows = loaded?.question === question ? loaded.rows : [];
  const error = failed?.key === key ? failed.message : null;
  const chosen = picked?.question === question ? picked.leads : NONE;
  // The page's latest counts setter, without reading the list again for it.
  const counts = useRef(onCounts);
  useEffect(() => {
    counts.current = onCounts;
  });
  const ask = {
    scope,
    stage: stage === TEST ? null : stage,
    search: query,
    test: stage === TEST,
    pipeline,
  };

  useEffect(() => {
    const controller = new AbortController();
    readLeads(
      {
        scope,
        stage: stage === TEST ? null : stage,
        search: query,
        test: stage === TEST,
        pipeline,
      },
      controller.signal,
    )
      .then((next) => {
        setLoaded({ key, question, page: next, rows: next.leads });
        if (next.stage_counts && stage !== TEST)
          counts.current?.(next.stage_counts);
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
  }, [key, question, scope, stage, query, pipeline]);

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
                  "Done"
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
          <InlineEmpty
            icon={query ? SearchX : Users}
            title={
              query
                ? "No leads match"
                : stage === TEST
                  ? "No test leads"
                  : `No leads in ${stageLabel}`
            }
            text={
              query
                ? "Try another name, city or the last digits of a number."
                : stage === TEST
                  ? "Test and sample leads show here, ready to clear."
                  : "A lead moves here from its own page, after a call."
            }
          />
        ) : (
          <>
            <ul className={styles.leadList} aria-label="Leads">
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
            {page.next_offset !== null ? (
              <div className={styles.more}>
                <Button onClick={more} disabled={loadingMore}>
                  {loadingMore ? "Loading…" : "Show more"}
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
        />
      ) : null}
      {bulk ? (
        <BulkSheet
          key={bulk.round}
          open={bulk.open}
          leadIds={[...chosen.keys()]}
          pipeline={pipeline}
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
