"use client";

/**
 * Pipeline numbers (Lead OS; the sales team's spec, section 9). Each lead is
 * counted once; conversions come from what happened to each lead, a skipped
 * stage counting as passed; Junk is left out of every conversion but has its
 * own numbers, by source (lead quality). Counts only: never money. Sellers see
 * their own leads; owners and admins the team's, per seller and per source.
 */

import { BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";

import { notify } from "../../notice-center";
import { Empty, Segmented, Skeleton } from "../../ui/kit";
import { LeadsError } from "../leads-client";
import {
  readPipelineReport,
  type PipelineReport,
  type ReportPeriod,
} from "./pipeline-client";
import styles from "./pipeline.module.css";

const PERIODS: { key: `${ReportPeriod}`; label: string }[] = [
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
];

export function percent(rate: number | null): string {
  return rate === null ? "–" : `${Math.round(rate * 100)}%`;
}

/** The headline over the "now" bars: the answer first. */
export function nowTitle(
  report: Pick<PipelineReport, "total" | "groups">,
): string {
  const active = report.groups.active ?? 0;
  return `${report.total} lead${report.total === 1 ? "" : "s"}, ${active} still being worked`;
}

function Bars({
  items,
  label,
}: {
  items: { key: string; label: string; count: number; tone?: string }[];
  label: string;
}) {
  const top = Math.max(1, ...items.map((item) => item.count));
  return (
    <ul className={styles.bars} aria-label={label}>
      {items.map((item) => (
        <li key={item.key} data-tone={item.tone}>
          <span className={styles.barLabel}>{item.label}</span>
          <span className={styles.barTrack} aria-hidden="true">
            <span
              className={styles.barFill}
              style={{ width: `${(item.count / top) * 100}%` }}
            />
          </span>
          <span className={styles.barValue}>{item.count}</span>
        </li>
      ))}
    </ul>
  );
}

export function PipelineDashboard({
  pipeline,
  initial = null,
}: {
  pipeline: string | null;
  /** A report already read (review fixtures and tests). */
  initial?: PipelineReport | null;
}) {
  const [days, setDays] = useState<ReportPeriod>(30);
  const [report, setReport] = useState<PipelineReport | null>(initial);
  useEffect(() => {
    const controller = new AbortController();
    readPipelineReport({ days, pipeline }, controller.signal).then(
      setReport,
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        notify({
          id: "pipeline-report",
          tone: "error",
          title: "The numbers didn't load",
          message: reason instanceof LeadsError ? reason.message : "Try again.",
        });
      },
    );
    return () => controller.abort();
  }, [days, pipeline]);

  const head = (
    <div className={styles.dashHead}>
      <Segmented
        label="Period"
        items={PERIODS}
        value={`${days}`}
        onChange={(next) => setDays(Number(next) as ReportPeriod)}
      />
    </div>
  );
  if (!report)
    return (
      <div className={styles.dashboard} aria-busy="true">
        {head}
        <div className={styles.kpis}>
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} height={72} />
          ))}
        </div>
        <Skeleton height={220} />
      </div>
    );
  if (!report.enough)
    return (
      <div className={styles.dashboard}>
        {head}
        <Empty
          icon={BarChart3}
          title={`Not enough leads yet: ${report.total}`}
          text="These numbers fill in from 10 leads. Add leads or connect your ad form."
        />
      </div>
    );

  const won = report.sellers.reduce((sum, row) => sum + row.won, 0);
  const meetings = report.sellers.reduce((sum, row) => sum + row.meetings, 0);
  const kpis = [
    { key: "active", label: "Being worked", value: report.groups.active ?? 0 },
    { key: "won", label: `Won in ${days} days`, value: won },
    { key: "meetings", label: "Meetings booked", value: meetings },
    {
      key: "overdue",
      label: "Late follow-ups",
      value: report.overdue,
      tone: report.overdue ? "bad" : undefined,
    },
    {
      key: "none",
      label: "No next step",
      value: report.no_next,
      tone: report.no_next ? "warn" : undefined,
    },
  ];
  const conversions = [report.first_connect, ...report.conversions];
  const best = [...report.sources]
    .filter((row) => row.created > 0)
    .sort((a, b) => (b.junk_rate ?? 0) - (a.junk_rate ?? 0));

  return (
    <div className={styles.dashboard}>
      {head}
      {report.mine ? <p className={styles.hint}>Your own leads.</p> : null}
      <section className={styles.kpis} aria-label="Today">
        {kpis.map((item) => (
          <div key={item.key} className={styles.kpi} data-tone={item.tone}>
            <span className={styles.kpiValue}>{item.value}</span>
            <span className={styles.kpiLabel}>{item.label}</span>
          </div>
        ))}
      </section>

      <section className={styles.panel} aria-label="Where leads are now">
        <h3>{nowTitle(report)}</h3>
        <Bars
          label="Leads in each stage now"
          items={report.stages.map((stage) => ({
            key: stage.step,
            label: stage.label,
            count: stage.count,
            tone: stage.group,
          }))}
        />
      </section>

      <section className={styles.panel} aria-label="Conversions">
        <h3>How leads move on, last {days} days</h3>
        <ul className={styles.conversions}>
          {conversions.map((item) => (
            <li key={item.key}>
              <span className={styles.convRate}>{percent(item.rate)}</span>
              <span className={styles.convText}>
                <strong>{item.label}</strong>
                <span>
                  {item.passed} of {item.entered} lead
                  {item.entered === 1 ? "" : "s"}
                  {item.key === "new_to_connect" &&
                  report.first_connect_minutes !== null
                    ? ` · first talk after ${report.first_connect_minutes} min`
                    : ""}
                  {item.key === "meeting_to_held" && report.show_rate !== null
                    ? ` · ${percent(report.show_rate)} of meetings happened`
                    : ""}
                </span>
              </span>
            </li>
          ))}
        </ul>
        <p className={styles.hint}>Junk leads are left out of these.</p>
      </section>

      <section className={styles.panel} aria-label="Why leads were lost">
        <h3>
          {report.lost_now.length
            ? `Lost most often: ${report.lost_now[0].label.toLowerCase()}`
            : "No lost leads"}
        </h3>
        {report.lost_now.length ? (
          <Bars
            label="Lost leads by reason"
            items={report.lost_now.slice(0, 7).map((item) => ({
              key: item.label,
              label: item.label,
              count: item.count,
              tone: "lost",
            }))}
          />
        ) : null}
      </section>

      <section className={styles.panel} aria-label="Junk by source">
        <h3>
          {report.junk_now
            ? `${report.junk_now} junk lead${report.junk_now === 1 ? "" : "s"}, ${report.junk_moves} in the last ${days} days`
            : "No junk leads"}
        </h3>
        {best.length ? (
          <ul className={styles.tableRows} aria-label="Lead quality by source">
            {best.map((row) => (
              <li key={row.key}>
                <span className={styles.rowName}>{row.label}</span>
                <span>{row.created} new</span>
                <span>{percent(row.connect_rate)} reached</span>
                <span
                  data-tone={(row.junk_rate ?? 0) >= 0.2 ? "bad" : undefined}
                >
                  {percent(row.junk_rate)} junk
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {!report.mine ? (
        <section className={styles.panel} aria-label="Sellers">
          <h3>Sellers, by leads won</h3>
          <ul className={styles.tableRows}>
            {report.sellers.map((row) => (
              <li key={row.key}>
                <span className={styles.rowName}>{row.label}</span>
                <span>{row.won} won</span>
                <span>{row.active} active</span>
                <span data-tone={row.overdue ? "bad" : undefined}>
                  {row.overdue} late
                </span>
                <span data-tone={row.no_next ? "warn" : undefined}>
                  {row.no_next} no next step
                </span>
                <span>
                  {row.first_response_minutes === null
                    ? "–"
                    : `${row.first_response_minutes} min to first talk`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
