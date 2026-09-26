"use client";

import {
  ArrowRight,
  BarChart3,
  Check,
  Clock3,
  FileText,
  Lightbulb,
  Play,
  Target,
  Trophy,
} from "lucide-react";
import type { ReportEvidence, SalesReport } from "./report-contract";
import styles from "./overview-dashboard.module.css";

export function OverviewDashboard({
  report,
  durationMs,
  momentCount,
  onOpenReview,
  onSelectEvidence,
}: {
  report: SalesReport;
  durationMs?: number;
  momentCount: number;
  onOpenReview: (number: string) => void;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
}) {
  const detail = report.overview;
  const strength = report.strengths[0];
  const change = report.improvements[0];
  const changeDetail = detail?.improvement_details.find(
    (item) => item.finding_index === 0,
  );
  const cards = [
    {
      label: "Key takeaway",
      icon: FileText,
      tone: "blue",
      title: report.verdict,
      text: report.summary,
      review: "14",
    },
    {
      label: "Keep doing this",
      icon: Trophy,
      tone: "mint",
      title: strength?.title ?? "No strength supplied",
      text:
        strength?.explanation ??
        "This report has no supported strength to show yet.",
      review: "01",
      source: strength?.evidence[0],
    },
    {
      label: "First thing to change",
      icon: Lightbulb,
      tone: "orange",
      title: change?.title ?? "No change supplied",
      text:
        changeDetail?.replacement_behavior ??
        change?.explanation ??
        "This report has no supported improvement to show yet.",
      review: change ? "02" : "14",
    },
    {
      label: "Outcome",
      icon: Target,
      tone: "cyan",
      title: detail?.outcome?.text ?? "No outcome supplied",
      text: "What the saved evidence shows—not a predicted result.",
      review: "14",
    },
    {
      label: "Next-call plan",
      icon: BarChart3,
      tone: "violet",
      title:
        detail?.next_call_focus?.behavior ??
        change?.title ??
        "No focus supplied",
      text:
        detail?.practice?.instructions ??
        "Review the source before choosing your next practice move.",
      review: "11",
    },
  ];
  const metrics = [
    {
      label: "Call duration",
      icon: Clock3,
      tone: "blue",
      value: durationMs
        ? `${Math.floor(durationMs / 60_000)}m ${String(Math.floor(durationMs / 1000) % 60).padStart(2, "0")}s`
        : "Unknown",
    },
    {
      label: "Highlights",
      icon: FileText,
      tone: "cyan",
      value: momentCount,
    },
    {
      label: "Suggested actions",
      icon: Check,
      tone: "mint",
      value: report.improvements.length,
    },
  ];
  return (
    <section className={styles.dashboard} aria-label="Call overview">
      <div className={styles.metrics} aria-label="Call metrics">
        {metrics.map(({ label, icon: Icon, tone, value }) => (
          <div key={label} className={styles.metric} data-tone={tone}>
            <span className={styles.icon}>
              <Icon aria-hidden="true" />
            </span>
            <div>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          </div>
        ))}
      </div>
      <div className={styles.grid}>
        {cards.map(
          ({ label, icon: Icon, tone, title, text, review, source }, index) => (
            <article
              key={label}
              className={styles.card}
              data-tone={tone}
              data-overview-card={index}
            >
              <header>
                <span className={styles.icon}>
                  <Icon aria-hidden="true" />
                </span>
                <h2>{label}</h2>
              </header>
              <h3>{title}</h3>
              <p>{text}</p>
              <footer>
                {source && (
                  <button
                    type="button"
                    className={styles.listen}
                    onClick={() => onSelectEvidence(source, strength!.title)}
                  >
                    <Play size={15} aria-hidden="true" /> Listen
                  </button>
                )}
                <button
                  type="button"
                  className={styles.open}
                  onClick={() => onOpenReview(review)}
                  aria-label={`Open review: ${label}`}
                >
                  {index === 4 ? "View plan" : "Open review"}
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              </footer>
            </article>
          ),
        )}
      </div>
    </section>
  );
}
