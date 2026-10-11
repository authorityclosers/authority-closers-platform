"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CircleAlert, PlayCircle, RefreshCw } from "lucide-react";

import { AdminShell } from "../../components/admin-shell";
import { Badge, Button, Panel, Skeleton, kitStyles } from "../../ui/kit";
import {
  loadAdminReport,
  type AdminReport,
  type AdminReportApiError,
} from "./admin-report-api";
import styles from "./reviewers.module.css";
import { istStamp } from "../../lib/time";

type ReportState =
  | { status: "loading"; report: null }
  | { status: "ready"; report: AdminReport }
  | { status: "error"; report: null; message: string; retryable: boolean };

type Finding = AdminReport["report"]["strengths"][number];

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function formatRetention(value: string): string {
  return istStamp(value, value);
}

function FindingList({
  title,
  items,
}: {
  title: string;
  items: readonly Finding[];
}) {
  return (
    <Panel title={title} sub={items.length || undefined}>
      {items.length === 0 ? (
        <p className={styles.body}>
          <span className={kitStyles.muted}>
            No evidence-backed items were saved.
          </span>
        </p>
      ) : (
        <ul className={styles.findings}>
          {items.map((item) => (
            <li key={`${item.title}:${item.explanation}`}>
              <strong>{item.title}</strong>
              <p>{item.explanation}</p>
              {item.evidence.length > 0 ? (
                <details className={styles.tech}>
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
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ReportBody({ report }: { report: AdminReport }) {
  const detail = report.report;
  return (
    <>
      <Panel
        title={report.recovery ? "Recovered draft" : "Saved draft"}
        tools={<Badge tone="warn">Not Dipak-adjudicated</Badge>}
      >
        <div className={styles.body}>
          <p className={styles.summary}>{detail.summary}</p>
          <p className={kitStyles.muted}>{detail.verdict}</p>
          <p className={kitStyles.muted}>{report.message}</p>
        </div>
      </Panel>

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

      <Panel title="Observed dimensions" sub={detail.dimensions.length}>
        <ul className={styles.findings}>
          {detail.dimensions.map((dimension) => (
            <li key={dimension.dimension_id}>
              <span className={styles.findingHead}>
                <strong>{dimension.label}</strong>
                <Badge>{dimension.status.replaceAll("_", " ")}</Badge>
              </span>
              <p>{dimension.observation}</p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Report provenance">
        <dl className={`${styles.facts} ${styles.body}`}>
          <div>
            <dt>Source</dt>
            <dd>{detail.source_label}</dd>
          </div>
          <div>
            <dt>Run</dt>
            <dd>
              <code>{report.run_id}</code>
            </dd>
          </div>
          <div>
            <dt>Recording</dt>
            <dd>
              <code>{report.recording_id}</code>
            </dd>
          </div>
          <div>
            <dt>Source revision</dt>
            <dd>{report.source.revision}</dd>
          </div>
          <div>
            <dt>Retention until</dt>
            <dd>{formatRetention(report.source.retention_until)}</dd>
          </div>
          <div>
            <dt>Report</dt>
            <dd>
              <code>{shortId(report.id)}</code>
            </dd>
          </div>
          {report.recovery ? (
            <div>
              <dt>Recovery</dt>
              <dd>
                {report.recovery.validation_state} · 0 provider calls · review
                blocked
              </dd>
            </div>
          ) : null}
        </dl>
      </Panel>
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
      title="Saved report"
      description="The saved, evidence-bound report for one run, as this Admin session may read it. Private, tenant-scoped and audited."
    >
      <div className={styles.workspace}>
        <span className={styles.actions}>
          <Link className={styles.back} href="/reviewers">
            <ArrowLeft size={14} aria-hidden="true" /> Back to reviewers
          </Link>
          {state.status === "ready" ? (
            <Link
              className={kitStyles.button}
              data-variant="secondary"
              href={`/calls/${encodeURIComponent(state.report.recording_id)}?run=${encodeURIComponent(state.report.run_id)}`}
            >
              <PlayCircle size={14} aria-hidden="true" /> Open in call review
            </Link>
          ) : null}
        </span>

        {state.status === "loading" ? (
          <div className={styles.skeleton} role="status" aria-live="polite">
            <span className={kitStyles.srOnly}>Opening the saved report</span>
            <Skeleton height={120} />
            <Skeleton height={220} />
          </div>
        ) : state.status === "error" ? (
          <p className={styles.note} role="alert">
            <CircleAlert size={14} aria-hidden="true" />
            <span>
              {state.message} The report stays protected by its recording and
              organisation boundary.
            </span>
            {state.retryable ? (
              <Button
                onClick={() => {
                  setState({ status: "loading", report: null });
                  setRequestNumber((current) => current + 1);
                }}
              >
                <RefreshCw size={14} aria-hidden="true" /> Try again
              </Button>
            ) : null}
          </p>
        ) : (
          <ReportBody report={state.report} />
        )}
      </div>
    </AdminShell>
  );
}
