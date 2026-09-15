"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CircleAlert, FileCheck2, LoaderCircle } from "lucide-react";

import { AdminShell } from "../../components/admin-shell";
import { SectionHeading } from "../../components/ops-primitives";
import {
  loadAdminReport,
  type AdminReport,
  type AdminReportApiError,
} from "./admin-report-api";
import styles from "./review-workspace.module.css";

type ReportState =
  | { status: "loading"; report: null }
  | { status: "ready"; report: AdminReport }
  | { status: "error"; report: null; message: string; retryable: boolean };

type Finding = AdminReport["report"]["strengths"][number];

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function formatRetention(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function FindingList({
  title,
  items,
}: {
  title: string;
  items: readonly Finding[];
}) {
  return (
    <section
      className={styles.reportSection}
      aria-labelledby={`report-${title}`}
    >
      <h3 id={`report-${title}`}>{title}</h3>
      {items.length === 0 ? (
        <p className={styles.panelIntro}>
          No evidence-backed items were saved.
        </p>
      ) : (
        <div className={styles.reportFindings}>
          {items.map((item) => (
            <article
              className={styles.reportFinding}
              key={`${item.title}:${item.explanation}`}
            >
              <h4>{item.title}</h4>
              <p>{item.explanation}</p>
              {item.evidence.length > 0 ? (
                <details className={styles.lineage}>
                  <summary>Source evidence</summary>
                  {item.evidence.map((evidence) => (
                    <blockquote
                      key={`${evidence.segment_id}:${evidence.start_ms}`}
                    >
                      “{evidence.quote}”
                      <cite>
                        {evidence.segment_id} · {evidence.start_ms}–
                        {evidence.end_ms} ms
                      </cite>
                    </blockquote>
                  ))}
                </details>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ReportBody({ report }: { report: AdminReport }) {
  const detail = report.report;
  return (
    <>
      <section
        className={styles.reportHero}
        aria-labelledby="report-summary-title"
      >
        <div className={styles.noticeIcon} aria-hidden="true">
          <FileCheck2 size={20} />
        </div>
        <div>
          <span className={styles.eyebrow}>
            {report.recovery
              ? "Recovered qualitative draft"
              : "Saved qualitative draft"}
          </span>
          <h2 id="report-summary-title">{detail.summary}</h2>
          <p>{detail.verdict}</p>
        </div>
        <span className={styles.noticeCode}>Not Dipak-adjudicated</span>
      </section>

      <div className={styles.reportGrid}>
        <FindingList title="Strengths" items={detail.strengths} />
        <FindingList
          title="Missed opportunities"
          items={detail.missed_opportunities}
        />
        <FindingList title="Improvements" items={detail.improvements} />
        <FindingList
          title="Objection analysis"
          items={detail.objection_analysis}
        />
        <FindingList title="Closing analysis" items={detail.closing_analysis} />
      </div>

      <section
        className={styles.reportSection}
        aria-labelledby="report-dimensions"
      >
        <h3 id="report-dimensions">Observed dimensions</h3>
        <div className={styles.reportDimensions}>
          {detail.dimensions.map((dimension) => (
            <article
              className={styles.reportDimension}
              key={dimension.dimension_id}
            >
              <div>
                <h4>{dimension.label}</h4>
                <span className={styles.pill}>
                  {dimension.status.replaceAll("_", " ")}
                </span>
              </div>
              <p>{dimension.observation}</p>
            </article>
          ))}
        </div>
      </section>

      <details className={styles.lineage}>
        <summary>Report provenance</summary>
        <span>
          <strong>Source</strong> {detail.source_label}
        </span>
        <span>
          <strong>Run</strong> <code>{report.run_id}</code>
        </span>
        <span>
          <strong>Recording</strong> <code>{report.recording_id}</code>
        </span>
        <span>
          <strong>Source revision</strong> {report.source.revision}
        </span>
        <span>
          <strong>Retention until</strong>{" "}
          {formatRetention(report.source.retention_until)}
        </span>
        <span>
          <strong>Report</strong> <code>{shortId(report.id)}</code>
        </span>
        {report.recovery ? (
          <span>
            <strong>Recovery</strong> {report.recovery.validation_state} · 0
            provider calls · review blocked
          </span>
        ) : null}
      </details>
    </>
  );
}

export function AdminReportPage({ runId }: { runId: string }) {
  const [state, setState] = useState<ReportState>({
    status: "loading",
    report: null,
  });
  const [requestNumber, setRequestNumber] = useState(0);

  const load = useCallback(() => {
    const controller = new AbortController();
    void loadAdminReport({ runId, signal: controller.signal }).then(
      (report) => setState({ status: "ready", report }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError = error as Partial<AdminReportApiError>;
        setState({
          status: "error",
          report: null,
          message:
            error instanceof Error
              ? error.message
              : "The report could not be opened.",
          retryable: apiError.retryable ?? true,
        });
      },
    );
    return () => controller.abort();
  }, [runId]);

  useEffect(() => load(), [load, requestNumber]);

  return (
    <AdminShell
      active="sales-xray"
      surface="operations"
      eyebrow="Sales Xray / Retained report"
      title="Open report"
      description="Review the saved evidence-bound report available to this authorized Admin session."
      footerText="Private report read · Access is tenant-scoped and audited"
    >
      <div className={styles.workspace}>
        <div className={styles.breadcrumbRow}>
          <Link className="back-link" href="/sales-xray/review">
            <ArrowLeft size={15} aria-hidden="true" /> Back to recordings
          </Link>
          <span className={styles.routeCode}>REPORT · {shortId(runId)}</span>
        </div>

        {state.status === "loading" ? (
          <div className={styles.queueState} role="status" aria-live="polite">
            <LoaderCircle size={26} className="spin" aria-hidden="true" />
            <strong>Opening the saved report</strong>
            <p>Checking retained permission and report evidence.</p>
          </div>
        ) : state.status === "error" ? (
          <div className={styles.queueState} role="alert">
            <CircleAlert size={28} aria-hidden="true" />
            <strong>{state.message}</strong>
            <p>
              This report remains protected by its recording and tenant
              boundary.
            </p>
            {state.retryable ? (
              <button
                className="button button-secondary"
                type="button"
                onClick={() => {
                  setState({ status: "loading", report: null });
                  setRequestNumber((current) => current + 1);
                }}
              >
                Try again
              </button>
            ) : null}
          </div>
        ) : (
          <section
            className={styles.panel}
            aria-labelledby="report-panel-title"
          >
            <SectionHeading
              eyebrow="Authorized Admin read"
              id="report-panel-title"
              title="Report evidence"
              body={state.report.message}
            />
            <ReportBody report={state.report} />
          </section>
        )}
      </div>
    </AdminShell>
  );
}
