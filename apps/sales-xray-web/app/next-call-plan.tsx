"use client";

import { useId, useState } from "react";
import {
  ArrowRight,
  CalendarDays,
  ChartNoAxesColumnIncreasing,
  Lightbulb,
  Play,
  Trophy,
} from "lucide-react";
import type { ReportEvidence, SalesReport } from "./report-contract";
import { formatTranscriptTime } from "./report-transcript";
import { ReviewDialog } from "./review-dialog";
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
  const prefix = useId();
  const [active, setActive] = useState(0);
  const [opened, setOpened] = useState<number | null>(null);
  const focus = report.overview?.next_call_focus;
  const practice = report.overview?.practice;
  const outcome = report.overview?.outcome;
  const first = report.improvements[0];
  const strength = report.strengths[0];
  const sections = [
    {
      label: "Keep doing this",
      short: "Keep",
      icon: Trophy,
      tone: "mint",
      title: strength?.title,
      text:
        strength?.explanation ??
        "No supported strength was supplied for this call.",
      extra: undefined,
      evidence: strength?.evidence ?? [],
    },
    {
      label: "Change first",
      short: "Change",
      icon: Lightbulb,
      tone: "orange",
      title: first?.title,
      text:
        focus?.behavior ??
        first?.explanation ??
        "No supported improvement was supplied for this call.",
      extra: focus ? { label: "Your target", text: focus.target } : undefined,
      evidence: first?.evidence ?? [],
    },
    {
      label: "Practise this",
      short: "Practise",
      icon: ChartNoAxesColumnIncreasing,
      tone: "violet",
      title: undefined,
      text:
        practice?.instructions ??
        "No practice instructions were supplied for this call.",
      extra: practice
        ? { label: "You’ve done it when", text: practice.success_condition }
        : undefined,
      evidence: [] as ReportEvidence[],
    },
  ];
  function evidenceButton(item: ReportEvidence, title: string, index: number) {
    return (
      <button
        key={`${item.segment_id}-${index}`}
        type="button"
        className={styles.evidence}
        onClick={() => onSelectEvidence(item, title)}
        aria-label={`Play source moment, ${item.start_ms} to ${item.end_ms}`}
      >
        <span className={styles.play}>
          <Play size={17} aria-hidden="true" />
        </span>
        <span>
          <strong>Listen to the source moment</strong>
          <small>
            {formatTranscriptTime(item.start_ms)}–
            {formatTranscriptTime(item.end_ms)}
          </small>
        </span>
        <ArrowRight size={17} aria-hidden="true" />
      </button>
    );
  }
  const selected = opened === null ? null : sections[opened];
  return (
    <section className={styles.plan} aria-label="Next-call plan">
      <header className={styles.header}>
        <span className={styles.headerIcon}>
          <CalendarDays aria-hidden="true" />
        </span>
        <div>
          <h2>Your next-call plan</h2>
          <p>Turn insights into a stronger next conversation.</p>
        </div>
        <small>Based on this call</small>
      </header>
      {outcome && (
        <aside className={styles.outcome} aria-label="Call outcome">
          <div>
            <h3>What happened in this call</h3>
            <p>{outcome.text}</p>
          </div>
          <div
            className={styles.outcomeSources}
            aria-label="Call outcome sources"
          >
            {outcome.evidence.map((item, index) => (
              <button
                key={`${item.segment_id}-${index}`}
                type="button"
                onClick={() => onSelectEvidence(item, "Call outcome")}
                aria-label={`Listen to call outcome at ${formatTranscriptTime(item.start_ms)}`}
              >
                <Play size={13} aria-hidden="true" />
                {formatTranscriptTime(item.start_ms)}
              </button>
            ))}
          </div>
        </aside>
      )}
      <nav className={styles.mobileTabs} aria-label="Plan sections">
        {sections.map((section, index) => (
          <button
            key={section.tone}
            type="button"
            aria-pressed={active === index}
            aria-controls={`${prefix}-${section.tone}`}
            data-tone={section.tone}
            onClick={() => setActive(index)}
          >
            {section.short}
          </button>
        ))}
      </nav>
      <div className={styles.grid}>
        {sections.map((section, index) => {
          const Icon = section.icon;
          return (
            <article
              key={section.tone}
              id={`${prefix}-${section.tone}`}
              className={styles.card}
              data-tone={section.tone}
              data-active={active === index}
            >
              <h3>
                <span className={styles.icon}>
                  <Icon aria-hidden="true" />
                </span>
                {section.label}
              </h3>
              <div className={styles.preview}>
                {section.title && <h4>{section.title}</h4>}
                <p>{section.text}</p>
                {section.extra && (
                  <p className={styles.target}>
                    <strong>{section.extra.label}:</strong> {section.extra.text}
                  </p>
                )}
              </div>
              <button
                className={styles.open}
                type="button"
                onClick={() => setOpened(index)}
              >
                Read full notes <ArrowRight size={16} aria-hidden="true" />
                <span className={styles.srOnly}>: {section.label}</span>
              </button>
            </article>
          );
        })}
      </div>
      {first?.evidence[0] ? (
        <aside
          className={styles.source}
          aria-label="Key evidence from this call"
        >
          <div>
            <h3>Key evidence from this call</h3>
            <blockquote>“{first.evidence[0].quote}”</blockquote>
          </div>
          {evidenceButton(first.evidence[0], first.title, 0)}
        </aside>
      ) : (
        <p className={styles.empty}>
          No timed source moment was supplied for this plan.
        </p>
      )}
      {report.preview?.sections.improvements.hidden_count && onUnlock ? (
        <button type="button" className={styles.unlock} onClick={onUnlock}>
          Sign in to see the rest of your plan{" "}
          <ArrowRight size={15} aria-hidden="true" />
        </button>
      ) : null}
      {selected && opened !== null && (
        <ReviewDialog
          open
          title={selected.label}
          position={`Plan ${opened + 1} of ${sections.length}`}
          eyebrow="Based on this call · draft coaching"
          onClose={() => setOpened(null)}
          onPrevious={() => setOpened(opened - 1)}
          onNext={() => setOpened(opened + 1)}
          previousDisabled={opened === 0}
          nextDisabled={opened === sections.length - 1}
          previousLabel="Previous"
          nextLabel="Next"
          closeLabel="Close plan notes"
        >
          <div className={styles.fullNotes}>
            {selected.title && <h3>{selected.title}</h3>}
            <p>{selected.text}</p>
            {selected.extra && (
              <p>
                <strong>{selected.extra.label}:</strong> {selected.extra.text}
              </p>
            )}
            {selected.evidence.map((item, index) => (
              <div
                key={`${item.segment_id}-${index}`}
                className={styles.fullSource}
              >
                {evidenceButton(item, selected.title ?? selected.label, index)}
                <blockquote>“{item.quote}”</blockquote>
              </div>
            ))}
          </div>
        </ReviewDialog>
      )}
    </section>
  );
}
