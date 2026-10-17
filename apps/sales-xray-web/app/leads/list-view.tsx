"use client";

import { Search, Users } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Empty, Panel, Segmented, Skeleton } from "../ui/kit";
import { LeadLine, type RowActions } from "./desk-view";
import {
  LeadsError,
  readLeads,
  STAGE_FILTERS,
  type LeadPage,
  type LeadRow,
} from "./leads-client";
import styles from "./leads.module.css";

type Scope = "mine" | "team" | "unassigned";

export function ListView({
  canManage,
  onOpen,
  version,
  actions,
}: {
  canManage: boolean;
  onOpen: (leadId: string) => void;
  version: number;
  actions?: RowActions;
}) {
  const params = useSearchParams();
  const initialStage = params.get("stage");
  const [scope, setScope] = useState<Scope>(canManage ? "team" : "mine");
  const [stage, setStage] = useState<string>(
    STAGE_FILTERS.some((item) => item.key === initialStage)
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
  // Results remember the question they answer; until the current one is
  // answered the list shows its skeleton. A refresh of the same question
  // (pull down, back in the app) keeps the rows on screen meanwhile.
  const question = JSON.stringify([scope, stage, query]);
  const key = JSON.stringify([scope, stage, query, version]);
  const page = loaded?.question === question ? loaded.page : null;
  const rows = loaded?.question === question ? loaded.rows : [];
  const error = failed?.key === key ? failed.message : null;

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    readLeads({ scope, stage, search: query }, controller.signal)
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
      const next = await readLeads({
        scope,
        stage,
        search: query,
        offset: page.next_offset,
      });
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

  return (
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
          {STAGE_FILTERS.map((item) => (
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
          title={query ? "No leads match" : "No leads here"}
          text={
            query
              ? "Try another name, city or the last digits of a phone number."
              : "Leads in this stage show here."
          }
        />
      ) : (
        <>
          <ul className={styles.leadList} aria-label="Leads">
            {rows.map((row) => (
              <LeadLine
                key={row.lead_id}
                row={row}
                onOpen={onOpen}
                showOwner={scope !== "mine"}
                actions={actions}
              />
            ))}
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
  );
}
