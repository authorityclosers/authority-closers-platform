"use client";

import { ArrowUpRight, Play, Target } from "lucide-react";
import type { ReportEvidence, SalesReport } from "./report-contract";
import styles from "./next-call-plan.module.css";

export function NextCallPlan({
  report,
  onSelectEvidence,
  onUnlock,
}: {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
}) {
  const focus = report.overview?.next_call_focus;
  const practice = report.overview?.practice;
  const first = report.improvements[0];
  return (
    <section className={styles.plan} aria-label="Next-call plan">
      <header className={styles.header}>
        <p className={styles.eyebrow}>NEXT-CALL PLAN</p>
        <h2>One supported move to practise next.</h2>
        <p>
          Keep the plan tied to this call. The source moment below remains the
          place to listen before you use it in a new conversation.
        </p>
      </header>
      {first ? (
        <article className={styles.focusCard}>
          <Target size={22} aria-hidden="true" />
          <div>
            <p className={styles.label}>FIRST CHANGE</p>
            <h3>{first.title}</h3>
            <p>{focus?.behavior ?? first.explanation}</p>
            {focus?.target && (
              <p className={styles.target}>
                <strong>Your target:</strong> {focus.target}
              </p>
            )}
          </div>
        </article>
      ) : (
        <p className={styles.empty}>No supported improvement was supplied.</p>
      )}
      {practice && (
        <article className={styles.practiceCard}>
          <p className={styles.label}>PRACTISE IT</p>
          <h3>{first?.title ?? "Saved practice"}</h3>
          <p>{practice.instructions}</p>
          <p>
            <strong>You’ve done it when:</strong> {practice.success_condition}
          </p>
        </article>
      )}
      {first?.evidence.map((item, index) => (
        <button
          key={`${item.segment_id}-${index}`}
          type="button"
          className={styles.evidence}
          onClick={() => onSelectEvidence(item, first.title)}
          aria-label={`Play source moment, ${item.start_ms} to ${item.end_ms}`}
        >
          <span className={styles.play} aria-hidden="true">
            <Play size={15} />
          </span>
          <span>
            <strong>Listen to the source moment</strong>
            <small>
              {Math.floor(item.start_ms / 60000)
                .toString()
                .padStart(2, "0")}
              :
              {Math.floor((item.start_ms / 1000) % 60)
                .toString()
                .padStart(2, "0")}
              –
              {Math.floor(item.end_ms / 60000)
                .toString()
                .padStart(2, "0")}
              :
              {Math.floor((item.end_ms / 1000) % 60)
                .toString()
                .padStart(2, "0")}
            </small>
          </span>
          <ArrowUpRight size={16} aria-hidden="true" />
        </button>
      ))}
      {report.preview?.sections.improvements.hidden_count && onUnlock ? (
        <button type="button" className={styles.unlock} onClick={onUnlock}>
          Continue free to keep the rest of your plan <ArrowUpRight size={15} />
        </button>
      ) : null}
    </section>
  );
}
