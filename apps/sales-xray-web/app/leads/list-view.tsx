"use client";

import { ListChecks, Search, Users } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import { Button, Empty, Panel, Segmented, Skeleton } from "../ui/kit";
import {
  DeleteLeadsSheet,
  SelectBar,
  SelectLine,
  type Doomed,
} from "./delete-leads";
import { LeadLine, type RowActions } from "./desk-view";
import {
  DELETE_LIMIT,
  LeadsError,
  readLeads,
  STAGE_FILTERS,
  type LeadPage,
  type LeadRow,
  type LeadsDeleted,
} from "./leads-client";
import selectStyles from "./delete-leads.module.css";
import styles from "./leads.module.css";

type Scope = "mine" | "team" | "unassigned";

// Owners and admins: test and sample leads in every stage, easy to clear.
const TEST = "test";
const NONE: ReadonlyMap<string, string> = new Map();

export function ListView({
  canManage,
  onOpen,
  version,
  actions,
  onChanged,
}: {
  canManage: boolean;
  onOpen: (leadId: string) => void;
  version: number;
  actions?: RowActions;
  /** Leads were deleted: the desk's counts read again. */
  onChanged?: () => void;
}) {
  const params = useSearchParams();
  const initialStage = params.get("stage");
  const filters = canManage
    ? [...STAGE_FILTERS, { key: TEST, label: "Test data" }]
    : STAGE_FILTERS;
  const [scope, setScope] = useState<Scope>(canManage ? "team" : "mine");
  const [stage, setStage] = useState<string>(
    filters.some((item) => item.key === initialStage)
      ? (initialStage as string)
      : "open",
  );
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
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
  const [confirm, setConfirm] = useState<{
    round: number;
    open: boolean;
    leads: Doomed[];
  } | null>(null);
  // Results remember the question they answer; until the current one is
  // answered the list shows its skeleton. A refresh of the same question
  // (pull down, back in the app) keeps the rows on screen meanwhile.
  const question = JSON.stringify([scope, stage, query]);
  const key = JSON.stringify([scope, stage, query, version]);
  const page = loaded?.question === question ? loaded.page : null;
  const rows = loaded?.question === question ? loaded.rows : [];
  const error = failed?.key === key ? failed.message : null;
  const chosen = picked?.question === question ? picked.leads : NONE;
  const ask = {
    scope,
    stage: stage === TEST ? null : stage,
    search: query,
    test: stage === TEST,
  };

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    readLeads(
      {
        scope,
        stage: stage === TEST ? null : stage,
        search: query,
        test: stage === TEST,
      },
      controller.signal,
    )
      .then((next) =>
        setLoaded({ key, question, page: next, rows: next.leads }),
      )
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
  }, [key, question, scope, stage, query]);

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
      <Panel
        title="All leads"
        sub={page ? `${page.total}` : undefined}
        tools={
          <label className={styles.search}>
            <Search size={14} aria-hidden="true" />
            <input
              type="search"
              value={search}
              placeholder="Name, company, city or phone"
              aria-label="Search leads"
              maxLength={80}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        }
      >
        <div className={styles.filters}>
          {canManage ? (
            <Segmented<Scope>
              label="Whose leads"
              value={scope}
              onChange={setScope}
              items={[
                { key: "team", label: "Everyone" },
                { key: "mine", label: "Mine" },
                { key: "unassigned", label: "No owner" },
              ]}
            />
          ) : null}
          <div className={styles.chips} role="group" aria-label="Stage">
            {filters.map((item) => (
              <button
                key={item.key}
                type="button"
                className={styles.chip}
                aria-pressed={stage === item.key}
                onClick={() => setStage(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          {canManage ? (
            <Button
              variant={selecting ? "primary" : "secondary"}
              className={selectStyles.selectToggle}
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
            </Button>
          ) : null}
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
          <Empty
            icon={Users}
            title={
              query
                ? "No leads match"
                : stage === TEST
                  ? "No test leads"
                  : "No leads here"
            }
            text={
              query
                ? "Try another name, city or the last digits of a phone number."
                : stage === TEST
                  ? "Test and sample leads show here, ready to clear."
                  : "Leads in this stage show here."
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
      </Panel>
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
