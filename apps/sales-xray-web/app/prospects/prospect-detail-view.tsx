"use client";

import {
  ArrowLeft,
  Calendar,
  Clock,
  ExternalLink,
  FileText,
  Phone,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { initials } from "../speaker-profiles";
import { useWorkspaceAccess } from "../workspace-access";
import {
  fetchProspectDetail,
  type ProspectCall,
  type ProspectDetail,
} from "../prospects-client";
import styles from "./prospects.module.css";
import { ProspectInformation } from "../prospect-information";
import { PageSkeleton } from "../shell/page-skeleton";
import informationStyles from "../prospect-information.module.css";
import { ProspectsAccessState } from "./prospects-access-state";
import { useLatestCallReport } from "../prospect-latest-call";

function formatCreatedDate(createdAt: string | null) {
  if (!createdAt) return "Never";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(createdAt));
  } catch {
    return createdAt;
  }
}

function formatDuration(durationSeconds: number) {
  const mins = Math.floor(durationSeconds / 60);
  const secs = durationSeconds % 60;
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs}s`;
}

export function ProspectDetailView({ prospectId }: { prospectId: string }) {
  const access = useWorkspaceAccess();
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  const contextKey = `${access?.context?.personId}:${access?.context?.tenantId}:${access?.context?.sessionId}:${prospectId}`;

  const [detail, setDetail] = useState<ProspectDetail | null>(null);
  const [loadedContext, setLoadedContext] = useState<string | null>(null);
  const [calls, setCalls] = useState<ProspectCall[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorContext, setErrorContext] = useState<string | null>(null);
  const pagination = useRef<AbortController | null>(null);

  const [attempt, setAttempt] = useState(0);
  // Call facts (blocker, commitments, next event) come from the latest Report.
  const latestCall = useLatestCallReport(
    calls,
    authenticated && loadedContext === contextKey,
  );

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();

    void fetchProspectDetail({
      prospectId,
      offset: 0,
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        setDetail(data);
        setLoadedContext(contextKey);
        setCalls(data.calls);
        setNextOffset(data.next_offset);
        setError(null);
        setLoading(false);
        setLoadingMore(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const msg =
          err instanceof Error
            ? err.message
            : "Prospect details could not be loaded. Try again; your completed work remains private.";
        setError(msg);
        setErrorContext(contextKey);
        setLoadedContext(null);
        setLoading(false);
      });

    return () => {
      controller.abort();
      pagination.current?.abort();
    };
  }, [authenticated, prospectId, attempt, contextKey]);

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    setAttempt((a) => a + 1);
  };

  const handleLoadMoreCalls = () => {
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
    void fetchProspectDetail({
      prospectId,
      offset: nextOffset,
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        setCalls((prev) => [...prev, ...data.calls]);
        setNextOffset(data.next_offset);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const msg =
          err instanceof Error
            ? err.message
            : "Prospect details could not be loaded. Try again; your completed work remains private.";
        setError(msg);
        setErrorContext(contextKey);
        setLoadedContext(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingMore(false);
      });
  };

  const prospect =
    authenticated && loadedContext === contextKey
      ? detail?.prospect
      : undefined;
  const visibleError = errorContext === contextKey ? error : null;
  const showLoading =
    authenticated &&
    (loading || (loadedContext !== contextKey && !visibleError));

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
        <Link href="/prospects" className={styles.backLink}>
          <ArrowLeft size={16} aria-hidden="true" />
          Back to Prospects
        </Link>

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

        {showLoading ? (
          <div aria-busy="true" aria-label="Loading prospect information">
            <PageSkeleton variant="list" />
          </div>
        ) : !prospect ? (
          <div className={styles.empty}>
            <p className={styles.emptyText}>This prospect is unavailable.</p>
          </div>
        ) : (
          <div>
            {/* Profile summary card */}
            <div className={styles.profileCard}>
              <div className={styles.profileTop}>
                <div className={styles.profileAvatar} aria-hidden="true">
                  {initials(prospect.name)}
                </div>
                <div className={styles.profileInfo}>
                  <h1 className={styles.prospectHeaderName}>{prospect.name}</h1>
                  <div className={styles.profileIdText}>
                    Prospect’s Information{" "}
                    {prospect.origin === "detected" && !prospect.confirmed_at
                      ? " · Detected"
                      : ""}
                  </div>
                </div>
              </div>
            </div>

            <ProspectInformation
              key={contextKey}
              prospect={prospect}
              calls={calls}
              latest={latestCall.latest}
              latestState={latestCall.state}
              onSaved={() => setAttempt((a) => a + 1)}
            />

            {/* Authorized calls list */}
            <details className={styles.callsContainer}>
              <summary className={styles.callsSectionTitle}>
                <Phone size={18} aria-hidden="true" />
                Opportunity history ({prospect.call_count} visible calls)
              </summary>

              {calls.length === 0 ? (
                <div className={styles.listPanel}>
                  <div className={styles.empty}>
                    <p className={styles.emptyText}>
                      No authorized calls associated with this prospect.
                    </p>
                  </div>
                </div>
              ) : (
                <div>
                  {calls.map((call) => (
                    <div
                      key={call.submission_id}
                      className={styles.callItem}
                      data-testid={`prospect-call-${call.submission_id}`}
                    >
                      <div className={styles.callItemHeader}>
                        <div>
                          <div className={styles.callItemTitle}>
                            {call.display_name ||
                              `Call ${call.submission_id.slice(0, 8)}`}
                          </div>
                          <div className={styles.callItemMeta}>
                            <Calendar size={13} aria-hidden="true" />
                            <span>{formatCreatedDate(call.created_at)}</span>
                            <span>•</span>
                            <Clock size={13} aria-hidden="true" />
                            <span>{formatDuration(call.duration_seconds)}</span>
                            {call.has_report ? null : (
                              <>
                                <span>•</span>
                                <span className={styles.badge}>
                                  Report not ready
                                </span>
                              </>
                            )}
                          </div>
                        </div>

                        <div className={styles.callItemActions}>
                          <Link
                            href={call.call_url}
                            className={styles.callActionLink}
                            aria-label={`View call ${call.submission_id}`}
                          >
                            <ExternalLink size={13} aria-hidden="true" />
                            View call
                          </Link>
                          {call.has_report && call.report_url ? (
                            <Link
                              href={call.report_url}
                              className={`${styles.callActionLink} ${styles.callActionReport}`}
                              aria-label={`Open report for call ${call.submission_id}`}
                            >
                              <FileText size={13} aria-hidden="true" />
                              Open report
                            </Link>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  ))}

                  {nextOffset !== null ? (
                    <div className={styles.loadMoreContainer}>
                      <button
                        type="button"
                        className={styles.loadMoreBtn}
                        onClick={handleLoadMoreCalls}
                        disabled={loadingMore}
                      >
                        {loadingMore
                          ? "Loading more calls..."
                          : "Load more calls"}
                      </button>
                    </div>
                  ) : null}
                </div>
              )}
            </details>
          </div>
        )}
      </div>
    </AcquisitionShell>
  );
}
