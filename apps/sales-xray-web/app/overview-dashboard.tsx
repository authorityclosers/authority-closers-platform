"use client";

import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Check,
  ChevronRight,
  Clock3,
  FileText,
  Lightbulb,
  ListChecks,
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
  reviewPoints,
  onOpenReview,
  onSelectEvidence,
}: {
  report: SalesReport;
  durationMs?: number;
  momentCount: number;
  reviewPoints: { number: string; label: string }[];
  onOpenReview: (number: string) => void;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
}) {
  const [activeCard, setActiveCard] = useState(0);
  const [desktopPage, setDesktopPage] = useState(0);
  const [reviewPage, setReviewPage] = useState(0);
  const detail = report.overview;
  const strength = report.strengths[0];
  const change = report.improvements[0];
  const changeDetail = detail?.improvement_details.find(
    (item) => item.finding_index === 0,
  );
  const pageCount = Math.max(1, Math.ceil(reviewPoints.length / 3));
  const safePage = Math.min(reviewPage, pageCount - 1);
  const cards = [
    {
      label: "Key takeaway",
      short: "Takeaway",
      icon: FileText,
      tone: "blue",
      title: report.verdict,
      text: report.summary,
      review: "14",
    },
    {
      label: "Keep doing this",
      short: "Keep",
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
      short: "Change",
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
      short: "Outcome",
      icon: Target,
      tone: "cyan",
      title: detail?.outcome?.text ?? "No outcome supplied",
      text: "What the saved evidence shows—not a predicted result.",
      review: "14",
    },
    {
      label: "Next-call plan",
      short: "Practice",
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
      label: "Source moments",
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
    {
      label: "Review points",
      icon: ListChecks,
      tone: "violet",
      value: reviewPoints.length,
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
              data-active={activeCard === index}
              data-page-visible={Math.floor(index / 3) === desktopPage}
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
        <article
          className={`${styles.card} ${styles.reviewCard}`}
          data-tone="neutral"
          data-overview-card="5"
          data-active={activeCard === 5}
          data-page-visible={desktopPage === 1}
        >
          <header>
            <span className={styles.icon}>
              <ListChecks aria-hidden="true" />
            </span>
            <h2>
              Review points <small>{reviewPoints.length} available</small>
            </h2>
          </header>
          <ol aria-label="Review points">
            {reviewPoints.map((item, index) => (
              <li key={item.number} hidden={Math.floor(index / 3) !== safePage}>
                <button
                  type="button"
                  data-insight-number={item.number}
                  onClick={() => onOpenReview(item.number)}
                >
                  <span>{index + 1}</span>
                  <strong>{item.label}</strong>
                  <ChevronRight size={15} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ol>
          <nav className={styles.reviewPager} aria-label="Review point pages">
            <span aria-live="polite">
              {safePage * 3 + 1}–
              {Math.min((safePage + 1) * 3, reviewPoints.length)} of{" "}
              {reviewPoints.length}
            </span>
            <button
              type="button"
              aria-label="Previous review points"
              disabled={safePage === 0}
              onClick={() => setReviewPage(safePage - 1)}
            >
              <ArrowLeft size={16} />
            </button>
            <button
              type="button"
              aria-label="Next review points"
              disabled={safePage === pageCount - 1}
              onClick={() => setReviewPage(safePage + 1)}
            >
              <ArrowRight size={16} />
            </button>
          </nav>
        </article>
      </div>
      <nav className={styles.desktopPager} aria-label="Overview pages">
        <button
          type="button"
          aria-pressed={desktopPage === 0}
          onClick={() => setDesktopPage(0)}
        >
          Takeaway, keep & change
        </button>
        <button
          type="button"
          aria-pressed={desktopPage === 1}
          onClick={() => setDesktopPage(1)}
        >
          Outcome, plan & review
        </button>
      </nav>
      <nav className={styles.mobilePager} aria-label="Overview cards">
        <div className={styles.cardArrows}>
          <span aria-live="polite">
            {activeCard + 1} of 6 <small>· Draft insights</small>
          </span>
          <button
            type="button"
            aria-label="Previous overview card"
            disabled={activeCard === 0}
            onClick={() => setActiveCard(activeCard - 1)}
          >
            <ArrowLeft size={18} />
          </button>
          <button
            type="button"
            aria-label="Next overview card"
            disabled={activeCard === 5}
            onClick={() => setActiveCard(activeCard + 1)}
          >
            <ArrowRight size={18} />
          </button>
        </div>
        <div className={styles.categories}>
          {[...cards.map((card) => card.short), "Review"].map(
            (label, index) => (
              <button
                key={label}
                type="button"
                data-tone={cards[index]?.tone ?? "neutral"}
                aria-pressed={activeCard === index}
                onClick={() => setActiveCard(index)}
              >
                {label}
              </button>
            ),
          )}
        </div>
      </nav>
    </section>
  );
}
