"use client";

import { ArrowRight, Info, RefreshCw, Search, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { initials } from "../speaker-profiles";
import { fetchProspectsList, type ProspectSummary } from "../prospects-client";
import styles from "./prospects.module.css";
import informationStyles from "../prospect-information.module.css";
import { PageSkeleton } from "../shell/page-skeleton";
import { ProspectsAccessState } from "./prospects-access-state";

function formatCreatedDate(createdAt: string | null) {
  if (!createdAt) return "Not available";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
      new Date(createdAt),
    );
  } catch {
    return createdAt;
  }
}

export function ProspectsListView() {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;

  const [prospects, setProspects] = useState<ProspectSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<string | null>(null);
  const [hoveredProspectId, setHoveredProspectId] = useState<string | null>(
    null,
  );
  const [attempt, setAttempt] = useState(0);
  const contextKey = `${access?.context?.personId}:${access?.context?.tenantId}:${access?.context?.sessionId}:${searchQuery}:${stageFilter}`;
  const [loadedContext, setLoadedContext] = useState<string | null>(null);
  const [errorContext, setErrorContext] = useState<string | null>(null);
  const pagination = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();

    void fetchProspectsList({
      search: searchQuery,
      stage: stageFilter,
      offset: 0,
      signal: controller.signal,
    })
      .then((page) => {
        if (controller.signal.aborted) return;
        setProspects(page.prospects);
        setTotal(page.total);
        setNextOffset(page.next_offset);
        setLoadedContext(contextKey);
        setError(null);
        setLoading(false);
        setLoadingMore(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const msg =
          err instanceof Error
            ? err.message
            : "Prospects could not be loaded. Try again; your completed work remains private.";
        setError(msg);
        setErrorContext(contextKey);
        setLoading(false);
      });

    return () => {
      controller.abort();
      pagination.current?.abort();
    };
  }, [authenticated, searchQuery, stageFilter, attempt, contextKey]);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value);
  };

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    setAttempt((a) => a + 1);
  };

  const handleLoadMore = () => {
    if (
      !authenticated ||
      loadedContext !== contextKey ||
      nextOffset === null ||
      loadingMore
    )
      return;
    setLoadingMore(true);
    const controller = new AbortController();
    pagination.current = controller;
    void fetchProspectsList({
      search: searchQuery,
      stage: stageFilter,
      offset: nextOffset,
      signal: controller.signal,
    })
      .then((page) => {
        if (controller.signal.aborted) return;
        setProspects((prev) => [...prev, ...page.prospects]);
        setNextOffset(page.next_offset);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const msg =
          err instanceof Error
            ? err.message
            : "Prospects could not be loaded. Try again; your completed work remains private.";
        setError(msg);
        setErrorContext(contextKey);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingMore(false);
      });
  };

  const current = authenticated && loadedContext === contextKey;
  const visibleError =
    authenticated && errorContext === contextKey ? error : null;
  const visibleProspects = current && !visibleError ? prospects : [];
  const showLoading = authenticated && (loading || (!current && !visibleError));

  if (!authenticated)
    return (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        loading={
          !access ||
          access.authenticated === null ||
          access.status === "loading"
        }
        active="prospects"
      >
        <div className={styles.root}>
          <ProspectsAccessState access={access} />
        </div>
      </AcquisitionShell>
    );

  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={!access}
      active="prospects"
    >
      <div className={styles.root}>
        <div className={styles.intro}>
          <div>
            <h1 className={styles.title}>Prospects</h1>
            <p className={styles.summary}>
              Cross-call prospect intelligence and conversation history.
              {current && !visibleError && total > 0
                ? ` (${total} recorded)`
                : ""}
            </p>
          </div>
        </div>

        {visibleError ? (
          <div className={informationStyles.cornerError} role="alert">
            <span>{visibleError}</span>
            <button
              type="button"
              className={styles.retryBtn}
              onClick={handleRetry}
            >
              <RefreshCw size={14} aria-hidden="true" />
              Try again
            </button>
          </div>
        ) : null}

        <div className={styles.listPanel}>
          <div className={styles.toolbar}>
            <div className={styles.searchBox}>
              <Search
                size={16}
                className={styles.searchIcon}
                aria-hidden="true"
              />
              <input
                type="search"
                className={styles.searchInput}
                placeholder="Search prospects by name..."
                value={searchQuery}
                onChange={handleSearchChange}
                aria-label="Search prospects"
              />
            </div>

            <div
              className={styles.filterGroup}
              role="group"
              aria-label="Stage filters"
            >
              <button
                type="button"
                className={`${styles.filterBtn}${stageFilter === null ? ` ${styles.filterBtnActive}` : ""}`}
                onClick={() => setStageFilter(null)}
                aria-pressed={stageFilter === null}
              >
                All
              </button>
              <button
                type="button"
                className={`${styles.filterBtn}${stageFilter === "__missing__" ? ` ${styles.filterBtnActive}` : ""}`}
                onClick={() =>
                  setStageFilter((prev) =>
                    prev === "__missing__" ? null : "__missing__",
                  )
                }
                aria-pressed={stageFilter === "__missing__"}
              >
                Missing stage
              </button>
            </div>
          </div>

          {showLoading ? (
            <div aria-busy="true" aria-label="Loading prospects">
              <PageSkeleton variant="list" />
            </div>
          ) : visibleError ? (
            <p className={styles.emptyText}>
              Prospects are unavailable. Try again.
            </p>
          ) : visibleProspects.length === 0 ? (
            <div className={styles.empty} data-testid="empty-prospects">
              <Users
                size={32}
                style={{ margin: "0 auto 12px", opacity: 0.4 }}
                aria-hidden="true"
              />
              <div className={styles.emptyTitle}>
                {searchQuery || stageFilter !== null
                  ? "No prospects match your search"
                  : "No prospects recorded yet"}
              </div>
              <p className={styles.emptyText}>
                {searchQuery || stageFilter !== null
                  ? "Try clearing the search query or stage filter."
                  : "Open an analysed call’s Where the Deal Stands section to save a new prospect or link it to an earlier prospect."}
              </p>
            </div>
          ) : (
            <div
              className={styles.prospectsList}
              role="feed"
              aria-label="Prospects list"
            >
              {visibleProspects.map((prospect) => (
                <div
                  key={prospect.prospect_id}
                  className={styles.prospectRow}
                  data-testid={`prospect-row-${prospect.prospect_id}`}
                  onMouseEnter={() =>
                    setHoveredProspectId(prospect.prospect_id)
                  }
                  onMouseLeave={() => setHoveredProspectId(null)}
                >
                  <Link
                    href={`/prospects/${prospect.prospect_id}`}
                    className={styles.prospectLeft}
                    aria-label={`Open prospect ${prospect.name}`}
                  >
                    <div className={styles.avatar} aria-hidden="true">
                      {initials(prospect.name)}
                    </div>
                    <div className={styles.prospectMeta}>
                      <span className={styles.prospectName}>
                        {prospect.name}
                      </span>
                      <div className={styles.prospectSub}>
                        <span>
                          {prospect.call_count}{" "}
                          {prospect.call_count === 1
                            ? "visible call"
                            : "visible calls"}
                        </span>
                        <span>•</span>
                        <span>
                          Last call: {formatCreatedDate(prospect.last_call)}
                        </span>
                      </div>
                    </div>
                  </Link>

                  <div className={styles.prospectRight}>
                    <span className={`${styles.badge} ${styles.badgeMissing}`}>
                      {prospect.stage ? prospect.stage : "Missing stage"}
                    </span>

                    <button
                      type="button"
                      className={styles.hoverTrigger}
                      aria-label={`Hover summary for ${prospect.name}`}
                      onMouseEnter={() =>
                        setHoveredProspectId(prospect.prospect_id)
                      }
                      onFocus={() => setHoveredProspectId(prospect.prospect_id)}
                      onBlur={() => setHoveredProspectId(null)}
                    >
                      <Info size={16} aria-hidden="true" />
                    </button>

                    <Link
                      href={`/prospects/${prospect.prospect_id}`}
                      className={styles.hoverTrigger}
                      aria-label={`View ${prospect.name}`}
                    >
                      <ArrowRight size={16} aria-hidden="true" />
                    </Link>

                    {hoveredProspectId === prospect.prospect_id ? (
                      <div
                        className={styles.hoverCard}
                        role="tooltip"
                        data-testid={`hover-card-${prospect.prospect_id}`}
                      >
                        <div className={styles.hoverCardRow}>
                          <span className={styles.hoverCardLabel}>
                            Prospect ID
                          </span>
                          <span
                            className={`${styles.hoverCardValue} ${styles.hoverCardMono}`}
                          >
                            {prospect.prospect_id}
                          </span>
                        </div>
                        <div className={styles.hoverCardRow}>
                          <span className={styles.hoverCardLabel}>
                            Visible calls
                          </span>
                          <span className={styles.hoverCardValue}>
                            {prospect.call_count}
                          </span>
                        </div>
                        <div className={styles.hoverCardRow}>
                          <span className={styles.hoverCardLabel}>
                            Last visible call
                          </span>
                          <span className={styles.hoverCardValue}>
                            {formatCreatedDate(prospect.last_call)}
                          </span>
                        </div>
                        <div className={styles.hoverCardRow}>
                          <span className={styles.hoverCardLabel}>
                            Next step
                          </span>
                          <span className={styles.hoverCardValue}>
                            {prospect.next_step ?? "None recorded"}
                          </span>
                        </div>
                        <div className={styles.hoverCardRow}>
                          <span className={styles.hoverCardLabel}>
                            Last promise
                          </span>
                          <span className={styles.hoverCardValue}>
                            {prospect.last_promise ?? "None recorded"}
                          </span>
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}

          {current && !visibleError && !showLoading && nextOffset !== null ? (
            <div className={styles.loadMoreContainer}>
              <button
                type="button"
                className={styles.loadMoreBtn}
                onClick={handleLoadMore}
                disabled={loadingMore}
              >
                {loadingMore ? "Loading more..." : "Load more prospects"}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </AcquisitionShell>
  );
}
