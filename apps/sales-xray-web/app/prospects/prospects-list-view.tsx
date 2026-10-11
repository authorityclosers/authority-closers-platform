"use client";

import { RefreshCw, Search, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { initials } from "../speaker-profiles";
import { prospectRow } from "../prospect-brief-model";
import {
  fetchProspectsList,
  ProspectsContractError,
  type ProspectSummary,
} from "../prospects-client";
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
  // No stage is stored yet; stage filters appear once the API offers stages.
  const [stagesOffered, setStagesOffered] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<string | null>(null);
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
        setStagesOffered(page.stage_filters.length > 0);
        setLoadedContext(contextKey);
        setError(null);
        setLoading(false);
        setLoadingMore(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const msg =
          // A contract mismatch is our fault: never show its technical text.
          err instanceof Error && !(err instanceof ProspectsContractError)
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
          // A contract mismatch is our fault: never show its technical text.
          err instanceof Error && !(err instanceof ProspectsContractError)
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
              Everyone you&apos;re selling to, their main problem and what
              happens next.
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

            {stagesOffered || stageFilter !== null ? (
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
            ) : null}
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
              {visibleProspects.map((prospect) => {
                const row = prospectRow(prospect);
                return (
                  <Link
                    key={prospect.prospect_id}
                    href={`/prospects/${prospect.prospect_id}`}
                    className={styles.prospectRow}
                    data-testid={`prospect-row-${prospect.prospect_id}`}
                    aria-label={`Open prospect ${prospect.name}`}
                  >
                    <span className={styles.prospectLeft}>
                      <span className={styles.avatar} aria-hidden="true">
                        {initials(prospect.name)}
                      </span>
                      <span className={styles.prospectMeta}>
                        <span className={styles.prospectName}>
                          {prospect.name}
                          {row.detected ? (
                            <span className={styles.detectedTag}>Detected</span>
                          ) : null}
                        </span>
                        <span className={styles.prospectSub}>
                          {row.subtitle ?? "Role and company not recorded"}
                        </span>
                      </span>
                    </span>
                    <span className={styles.prospectProblem}>
                      {row.problem ?? (
                        <span className={styles.muted}>
                          Main problem unknown
                        </span>
                      )}
                    </span>
                    <span className={styles.prospectStage}>
                      {prospect.stage ? (
                        <span className={styles.badge}>{prospect.stage}</span>
                      ) : (
                        <span className={styles.muted}>No stage yet</span>
                      )}
                    </span>
                    <span className={styles.prospectNext}>
                      {row.nextStep ?? (
                        <span className={styles.muted}>No next step</span>
                      )}
                    </span>
                    <span className={styles.prospectLast}>
                      {formatCreatedDate(prospect.last_call)}
                      <small>
                        {prospect.call_count}{" "}
                        {prospect.call_count === 1
                          ? "visible call"
                          : "visible calls"}
                      </small>
                    </span>
                  </Link>
                );
              })}
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
