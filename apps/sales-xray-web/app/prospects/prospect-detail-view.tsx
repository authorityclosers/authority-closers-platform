"use client";

import {
  ArrowLeft,
  Calendar,
  Clock,
  ExternalLink,
  FileText,
  HelpCircle,
  LoaderCircle,
  Phone,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { formatClock } from "../lightbox/time";
import { initials } from "../speaker-profiles";
import { useWorkspaceAccess } from "../workspace-access";
import {
  fetchProspectDetail,
  type ProspectCall,
  type ProspectDetail,
} from "../prospects-client";
import styles from "./prospects.module.css";

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
  const authenticated = access?.authenticated === true;

  const [detail, setDetail] = useState<ProspectDetail | null>(null);
  const [calls, setCalls] = useState<ProspectCall[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [attempt, setAttempt] = useState(0);

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
        setCalls(data.calls);
        setNextOffset(data.next_offset);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const msg =
          err instanceof Error
            ? err.message
            : "Prospect details could not be loaded. Try again; your completed work remains private.";
        setError(msg);
        setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [authenticated, prospectId, attempt]);

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    setAttempt((a) => a + 1);
  };

  const handleLoadMoreCalls = () => {
    if (nextOffset === null || loadingMore) return;
    setLoadingMore(true);
    void fetchProspectDetail({
      prospectId,
      offset: nextOffset,
    })
      .then((data) => {
        setCalls((prev) => [...prev, ...data.calls]);
        setNextOffset(data.next_offset);
      })
      .catch((err: unknown) => {
        const msg =
          err instanceof Error
            ? err.message
            : "Prospect details could not be loaded. Try again; your completed work remains private.";
        setError(msg);
      })
      .finally(() => {
        setLoadingMore(false);
      });
  };

  const prospect = detail?.prospect;
  const showLoading = authenticated && loading;

  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={!access}
      active="prospects"
    >
      <div className={styles.root}>
        <Link href="/prospects" prefetch={false} className={styles.backLink}>
          <ArrowLeft size={16} aria-hidden="true" />
          Back to Prospects
        </Link>

        {error ? (
          <div className={styles.errorBanner} role="alert">
            <span>{error}</span>
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
          <div className={styles.empty}>
            <LoaderCircle
              size={24}
              style={{
                animation: "spin 1s linear infinite",
                margin: "0 auto 12px",
              }}
              aria-hidden="true"
            />
            <p className={styles.emptyText}>Loading prospect details...</p>
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
                    ID: {prospect.prospect_id} • Revision {prospect.revision}
                  </div>
                </div>
              </div>

              {/* Visibly missing fields grid */}
              <div className={styles.missingGrid}>
                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>Photo</div>
                  <div className={styles.missingItemValue}>
                    {prospect.photo_url
                      ? "Provided"
                      : "Missing (using initials)"}
                  </div>
                </div>

                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>Contact</div>
                  <div className={styles.missingItemValue}>
                    {prospect.contact ? prospect.contact : "No contact details"}
                  </div>
                </div>

                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>
                    Confirmed profile
                  </div>
                  <div className={styles.missingItemValue}>
                    {prospect.fields.length > 0
                      ? `${prospect.fields.length} confirmed`
                      : "No confirmed profile fields"}
                  </div>
                </div>

                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>Stage</div>
                  <div className={styles.missingItemValue}>
                    {prospect.stage ? prospect.stage : "Unassigned"}
                  </div>
                </div>

                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>Tags</div>
                  <div className={styles.missingItemValue}>
                    {prospect.tags.length > 0
                      ? prospect.tags.join(", ")
                      : "No tags"}
                  </div>
                </div>

                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>Buyer readiness</div>
                  <div className={styles.missingItemValue}>
                    {prospect.buyer_intent ? "Available" : "Not scored"}
                  </div>
                </div>

                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>Next step</div>
                  <div className={styles.missingItemValue}>
                    {prospect.next_step ? prospect.next_step : "None recorded"}
                  </div>
                </div>

                <div className={styles.missingItem}>
                  <div className={styles.missingItemLabel}>Last promise</div>
                  <div className={styles.missingItemValue}>
                    {prospect.last_promise
                      ? prospect.last_promise
                      : "None recorded"}
                  </div>
                </div>
              </div>
            </div>

            {/* Hypothesis boundary notice */}
            <div className={styles.hypothesisBanner} role="note">
              <HelpCircle
                size={18}
                aria-hidden="true"
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <div>
                <strong>Per-call hypothesis boundary:</strong> Each snapshot
                shown below is an interpretation from that specific call.
                Snapshots remain separate from confirmed profile fields; no
                unverified facts or scores are manufactured.
              </div>
            </div>

            {/* Authorized calls list */}
            <div className={styles.callsContainer}>
              <h2 className={styles.callsSectionTitle}>
                <Phone size={18} aria-hidden="true" />
                Authorized Calls ({prospect.call_count})
              </h2>

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
                            <span>•</span>
                            <span className={styles.badge}>
                              State: {call.state}
                            </span>
                            <span>•</span>
                            <span className={styles.badge}>Score: —</span>
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

                      {/* Snapshot interpretations if present */}
                      {call.snapshot ? (
                        <div
                          className={styles.snapshotBox}
                          data-testid={`call-snapshot-${call.snapshot.snapshot_id}`}
                        >
                          <div className={styles.snapshotBoxHeader}>
                            <span className={styles.snapshotBoxTitle}>
                              Per-call hypothesis ({call.snapshot.snapshot_kind}
                              )
                            </span>
                            <span className={styles.snapshotProvenance}>
                              rev {call.snapshot.source_revision} •{" "}
                              {call.snapshot.transcript_revision} •{" "}
                              {call.snapshot.source_sha256.slice(0, 8)}
                            </span>
                          </div>

                          {call.snapshot.interpretations.map((interp, idx) => (
                            <div
                              key={idx}
                              className={styles.interpretationItem}
                            >
                              <span className={styles.interpretationKind}>
                                {interp.interpretation_kind}
                              </span>
                              <p className={styles.interpretationText}>
                                {interp.source.text}
                              </p>
                              <p className={styles.interpretationConcern}>
                                Meaning: {interp.possible_concern}
                              </p>

                              {interp.source.evidence.map((ev) => (
                                <div
                                  key={`${ev.segment_id}-${ev.start_ms}`}
                                  className={styles.evidenceClip}
                                >
                                  <div className={styles.evidenceQuote}>
                                    &ldquo;{ev.quote}&rdquo;
                                  </div>
                                  <div className={styles.evidenceMeta}>
                                    Segment {ev.segment_id} •{" "}
                                    {formatClock(ev.start_ms)} –{" "}
                                    {formatClock(ev.end_ms)}
                                  </div>
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      ) : null}
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
            </div>
          </div>
        )}
      </div>
    </AcquisitionShell>
  );
}
