"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Lightbulb } from "lucide-react";
import { Glyph } from "./lightbox/glyph";
import { ClipListenButton } from "./source-waveform";
import { NextCallPlan } from "./next-call-plan";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import styles from "./report-coaching.module.css";

export type ReportCoachingProps = {
  report: SalesReport;
  transcript?: Transcript;
  callId?: string | null;
  durationMs?: number;
  onSelectEvidence?: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
};

const SESSION_KEY_PREFIX = "ac:coaching:";

export function ReportCoaching({
  report,
  transcript,
  callId,
  durationMs,
  onSelectEvidence,
  onUnlock,
}: ReportCoachingProps) {
  const sessionKey = `${SESSION_KEY_PREFIX}${callId ?? "default"}`;

  const [unlocked, setUnlocked] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return sessionStorage.getItem(sessionKey) === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      if (sessionStorage.getItem(sessionKey) === "true") {
        setUnlocked(true);
      }
    } catch {}
  }, [sessionKey]);

  const handleUnlock = () => {
    setUnlocked(true);
    try {
      sessionStorage.setItem(sessionKey, "true");
    } catch {}
  };

  const strength = report.strengths?.[0];
  const primary = report.improvements?.[0];
  const detail = (report as { detail?: Record<string, any> })?.detail ?? null;
  const primaryDetail = detail?.primary_improvement ?? null;

  const listen = (evidence: ReportEvidence, title: string) =>
    onSelectEvidence ? (
      <ClipListenButton
        className={styles.listen}
        startMs={evidence.start_ms}
        endMs={evidence.end_ms}
        onClick={() => onSelectEvidence(evidence, title)}
        label={title}
      />
    ) : null;

  return (
    <div
      className={styles.coaching}
      aria-label="Call coaching"
      data-coaching-section
    >
      {!unlocked ? (
        <div className={styles.coachingGate} data-coaching-gate>
          <article className={styles.gateCard} data-coaching-card="prompt">
            <div className={styles.gateIcon}>
              <Lightbulb size={26} aria-hidden="true" />
            </div>
            <h2>Want tips for your next call?</h2>
            <p>
              Get targeted coaching, habits to repeat, and your next-call focus
              based on this conversation.
            </p>
            <button
              type="button"
              className={styles.coachButton}
              data-coach-trigger
              onClick={handleUnlock}
            >
              Coach me on this call
            </button>
          </article>
        </div>
      ) : (
        <div className={styles.coachingContent} data-coaching-content>
          <div className={styles.summaryRows} data-coaching-summary>
            {/* Keep doing */}
            <article
              className={styles.summaryRow}
              data-coaching-card="keep"
              data-overview-card="1"
              data-tone="keep"
            >
              <p className={styles.rowLabel}>
                <Glyph name="strength" size={16} /> Keep doing
              </p>
              <div className={styles.rowBody}>
                <h3 className={styles.rowTitle}>
                  {strength?.title ?? "No strength supplied"}
                </h3>
                <p>
                  {strength?.explanation ??
                    "This report has no supported strength to show yet."}
                </p>
                {strength && strength.evidence[0] && (
                  <div className={styles.rowActions}>
                    {listen(strength.evidence[0], strength.title)}
                  </div>
                )}
              </div>
            </article>

            {/* Change first */}
            <article
              className={styles.summaryRow}
              data-coaching-card="change"
              data-overview-card="2"
              data-tone="change"
            >
              <p className={styles.rowLabel}>
                <Glyph name="focus" size={16} /> Change first
              </p>
              <div className={styles.rowBody}>
                <h3 className={styles.rowTitle}>
                  {primary?.title ?? "No change supplied"}
                </h3>
                <p>
                  {primaryDetail ? (
                    <>
                      <strong>Try this:</strong>{" "}
                      {primaryDetail.replacement_behavior}
                    </>
                  ) : (
                    (primary?.explanation ??
                    "This report has no supported improvement to show yet.")
                  )}
                </p>
                {primary && primary.evidence[0] && (
                  <div className={styles.rowActions}>
                    {listen(primary.evidence[0], primary.title)}
                  </div>
                )}
              </div>
            </article>

            {/* Next call */}
            <article
              className={styles.summaryRow}
              data-coaching-card="next"
              data-overview-card="4"
              data-tone="next"
            >
              <p className={styles.rowLabel}>
                <Glyph name="chapter-plan" size={16} /> Next call
              </p>
              <div className={styles.rowBody}>
                <h3 className={styles.rowTitle}>
                  {detail?.next_call_focus?.behavior ??
                    primary?.title ??
                    "No focus supplied"}
                </h3>
                <p>
                  {detail?.practice?.instructions ??
                    "Review the source before choosing your next practice move."}
                </p>
              </div>
            </article>
          </div>

          {/* Next-call plan */}
          <div className={styles.nextCallPlanSection}>
            <NextCallPlan
              report={report}
              callId={callId ?? null}
              transcript={transcript}
              onSelectEvidence={onSelectEvidence}
              onUnlock={onUnlock}
            />
          </div>
        </div>
      )}
    </div>
  );
}
