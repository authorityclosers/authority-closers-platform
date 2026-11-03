"use client";

/**
 * Analytics: the owner's one page of numbers (Lead OS; the sales team's spec,
 * section 9; owner Analytics, 2 Nov 2026, design cleared by ux-audit). Outcomes
 * first, then campaigns (Live, Paused, Ended: old against live), salespeople,
 * and the call reports' coaching line; where leads stand, how they move on, why
 * they were lost and the top cities wait under See more (Dipak's brief: detailed
 * charts under "See more"). Each lead is counted once; conversions come from
 * what happened to each lead, a skipped stage counting as passed; Junk is left
 * out of every conversion. All time is the one period that counts old leads
 * brought in as history. Counts only: never money. Sellers see their own leads.
 */

import { BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";

import { notify } from "../../notice-center";
import { ShareLine } from "../../organisation/insights/insights-charts";
import {
  DEFAULT_FILTERS,
  INSIGHTS_PATH,
  parseInsights,
  queryOf,
  type Insights,
  type RangeKey,
} from "../../organisation/insights/insights-data";
import { Empty, Segmented, Skeleton } from "../../ui/kit";
import { LeadsError } from "../leads-client";
import {
  readPipelineReport,
  type CampaignRow,
  type CampaignStatus,
  type GroupRow,
  type PipelineReport,
  type ReportPeriod,
} from "./pipeline-client";
import styles from "./pipeline.module.css";

const PERIODS: { key: `${ReportPeriod}`; label: string }[] = [
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
  { key: "0", label: "All time" },
];
const STATUS_WORDS: Record<CampaignStatus, string> = {
  live: "Live",
  paused: "Paused",
  ended: "Ended",
};
const METRICS = [
  { key: "won", label: "Won" },
  { key: "calls", label: "Calls" },
  { key: "talk", label: "Talk time" },
] as const;
type Metric = (typeof METRICS)[number]["key"];
// A campaign with fewer new leads than this is too small to call best.
const FAIR_SIZE = 10;

export function percent(rate: number | null): string {
  return rate === null ? "–" : `${Math.round(rate * 100)}%`;
}

/** "34 min", "2 h 5 min", or a dash when nothing was timed. */
export function minutesText(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value < 60) return `${value} min`;
  const hours = Math.floor(value / 60);
  const rest = value % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** Talk time in words, from seconds. */
export function talkText(seconds: number): string {
  return seconds < 60 ? `${seconds} s` : minutesText(Math.round(seconds / 60));
}

/** Leads won for every 100 new leads, one decimal; null with no new leads. */
export function wonPer100(
  row: Pick<GroupRow, "won" | "created">,
): number | null {
  return row.created > 0
    ? Math.round((row.won / row.created) * 1000) / 10
    : null;
}

/** The headline over the "now" bars: the answer first. */
export function nowTitle(
  report: Pick<PipelineReport, "total" | "groups">,
): string {
  const active = report.groups.active ?? 0;
  return `${report.total} lead${report.total === 1 ? "" : "s"}, ${active} still being worked`;
}

function sum(rows: GroupRow[]): Pick<GroupRow, "won" | "created"> {
  return rows.reduce(
    (total, row) => ({
      won: total.won + row.won,
      created: total.created + row.created,
    }),
    { won: 0, created: 0 },
  );
}

/** The campaigns' answer: live against old when both are big enough, else the best. */
export function campaignTitle(rows: CampaignRow[]): string {
  const live = sum(rows.filter((row) => row.status === "live"));
  const ended = sum(rows.filter((row) => row.status === "ended"));
  const liveRate = wonPer100(live);
  const endedRate = wonPer100(ended);
  if (
    live.created >= FAIR_SIZE * 2 &&
    ended.created >= FAIR_SIZE * 2 &&
    liveRate !== null &&
    endedRate !== null &&
    liveRate > 0 &&
    endedRate > 0
  ) {
    const ratio = liveRate / endedRate;
    if (ratio >= 1.5)
      return `Live campaigns win ${Math.round(ratio)} times as often as ended ones`;
    if (ratio <= 1 / 1.5)
      return `Ended campaigns won ${Math.round(1 / ratio)} times as often as live ones`;
    return "Live and ended campaigns win about as often";
  }
  const best = rows
    .filter((row) => row.created >= FAIR_SIZE && row.won > 0)
    .sort((a, b) => (wonPer100(b) ?? 0) - (wonPer100(a) ?? 0))[0];
  return best
    ? `${best.label} wins most: ${wonPer100(best)} per 100 leads`
    : "Won per 100 leads, by campaign";
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

/** One bar a row, its value said beside its name and its details under it. */
function MeasureRows({
  rows,
  label,
}: {
  rows: {
    key: string;
    name: string;
    value: number;
    shown: string;
    meta: string;
    quiet?: boolean;
  }[];
  label: string;
}) {
  const top = Math.max(0, ...rows.map((row) => row.value));
  return (
    <ul className={styles.measures} aria-label={label}>
      {rows.map((row) => (
        <li key={row.key} data-quiet={row.quiet || undefined}>
          <span className={styles.measureName}>{row.name}</span>
          <span className={styles.measureValue}>{row.shown}</span>
          <span className={styles.barTrack} aria-hidden="true">
            <span
              className={styles.barFill}
              style={{ width: top > 0 ? `${(row.value / top) * 100}%` : "0%" }}
            />
          </span>
          <span className={styles.measureMeta}>{row.meta}</span>
        </li>
      ))}
    </ul>
  );
}

function campaignMeta(row: CampaignRow): string {
  const genuine = row.created - row.junk;
  const keen =
    genuine > 0 && row.interested !== undefined
      ? row.interested / genuine
      : null;
  return [
    `${row.created} lead${row.created === 1 ? "" : "s"}`,
    `${percent(row.connect_rate)} reached`,
    `${percent(keen)} interested`,
    `${row.won} won`,
    `first call ${row.history ? "–" : minutesText(row.first_response_minutes)}`,
  ].join(" · ");
}

function Campaigns({ rows }: { rows: CampaignRow[] }) {
  const measure = (row: CampaignRow) => ({
    key: row.key,
    name: row.label,
    value: wonPer100(row) ?? 0,
    shown: wonPer100(row) === null ? "–" : String(wonPer100(row)),
    meta: campaignMeta(row),
    quiet: row.status !== "live",
  });
  const groups = (["live", "paused", "ended"] as const)
    .map((status) => ({
      status,
      rows: rows.filter((row) => row.status === status),
    }))
    .filter((group) => group.rows.length > 0);
  return (
    <section className={styles.panel} aria-label="Campaigns">
      <h3>{campaignTitle(rows)}</h3>
      <p className={styles.panelSub}>Won per 100 new leads</p>
      {groups.map((group) => {
        const total = sum(group.rows);
        const head = (
          <span className={styles.groupHead}>
            <span>
              {STATUS_WORDS[group.status]} · {total.created} lead
              {total.created === 1 ? "" : "s"}
            </span>
            <span>{wonPer100(total) ?? "–"}</span>
          </span>
        );
        const list = (
          <MeasureRows
            rows={group.rows.map(measure)}
            label={`${STATUS_WORDS[group.status]} campaigns`}
          />
        );
        // Ended campaigns fold under one line, so the live ones stay in sight.
        return group.status === "ended" ? (
          <details key={group.status} className={styles.fold}>
            <summary>
              {head}
              <span className={styles.foldHint}>
                {group.rows.length} ended campaign
                {group.rows.length === 1 ? "" : "s"}
              </span>
            </summary>
            {list}
          </details>
        ) : (
          <div key={group.status} className={styles.group}>
            {head}
            {list}
          </div>
        );
      })}
    </section>
  );
}

function Salespeople({ rows }: { rows: GroupRow[] }) {
  const [metric, setMetric] = useState<Metric>("won");
  const people = rows.filter((row) => row.key !== "none");
  const unowned = rows.find((row) => row.key === "none");
  const value = (row: GroupRow) =>
    metric === "won"
      ? row.won
      : metric === "calls"
        ? (row.calls ?? 0)
        : (row.talk_seconds ?? 0);
  const sorted = [...people].sort(
    (a, b) => value(b) - value(a) || a.label.localeCompare(b.label),
  );
  const leader = sorted[0];
  const title =
    !leader || value(leader) === 0
      ? metric === "won"
        ? "No wins yet in this period"
        : "No calls yet in this period"
      : metric === "won"
        ? `${leader.label} wins most`
        : metric === "calls"
          ? `${leader.label} makes the most calls`
          : `${leader.label} talks to buyers the longest`;
  return (
    <section className={styles.panel} aria-label="Salespeople">
      <h3>{title}</h3>
      <Segmented
        label="Compare salespeople by"
        items={METRICS.map((item) => ({ key: item.key, label: item.label }))}
        value={metric}
        onChange={(next) => setMetric(next as Metric)}
      />
      <MeasureRows
        label="Salespeople"
        rows={sorted.map((row) => ({
          key: row.key,
          name: row.label,
          value: value(row),
          shown:
            metric === "won"
              ? `${row.won} won`
              : metric === "calls"
                ? `${row.calls ?? 0} calls`
                : talkText(row.talk_seconds ?? 0),
          meta: [
            `${row.created} new lead${row.created === 1 ? "" : "s"}`,
            `${row.calls ?? 0} calls`,
            `${talkText(row.talk_seconds ?? 0)} talk`,
            `first call ${minutesText(row.first_response_minutes)}`,
          ].join(" · "),
        }))}
      />
      {unowned && unowned.leads > 0 ? (
        <p className={styles.hint}>
          {unowned.leads} lead{unowned.leads === 1 ? " has" : "s have"} no
          salesperson.
        </p>
      ) : null}
    </section>
  );
}

async function readInsights(range: RangeKey, signal: AbortSignal) {
  const response = await fetch(
    INSIGHTS_PATH + queryOf({ ...DEFAULT_FILTERS, range }),
    {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { accept: "application/json" },
      signal,
    },
  );
  if (!response.ok) throw new Error(`Read failed (${response.status})`);
  return parseInsights(await response.json());
}

/**
 * The call reports' coaching line, exactly as Insights shows it: the share of
 * skill moments needing work, by week or month. Lower is better; no score.
 * Shown only when it has two points to draw.
 */
function CallQuality({ days }: { days: ReportPeriod }) {
  const [data, setData] = useState<Insights | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const range: RangeKey = days === 0 ? "all" : days === 90 ? "90d" : "30d";
    readInsights(range, controller.signal).then(setData, () => setData(null));
    return () => controller.abort();
  }, [days]);
  const known = (data?.trend ?? []).filter(
    (point) => point.needsAttentionShare !== null,
  );
  if (!data || known.length < 2) return null;
  const first = known[0].needsAttentionShare;
  const last = known[known.length - 1].needsAttentionShare;
  const better = (last ?? 0) < (first ?? 0);
  return (
    <section className={styles.panel} aria-label="Call quality">
      <h3>
        {better ? "Fewer" : "More"} skill moments need work: {percent(first)} to{" "}
        {percent(last)}
      </h3>
      <p className={styles.panelSub}>
        From the call reports, as in Insights. Lower is better.
      </p>
      <ShareLine
        points={data.trend.map((point) => ({
          at: point.at,
          share: point.needsAttentionShare,
        }))}
        unit={data.window.unit}
        label="needing work"
      />
      <a className={styles.more} href="/organisation/insights">
        Open Insights
      </a>
    </section>
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

  const won = report.sellers.reduce((total, row) => total + row.won, 0);
  // Outcomes first (ux-audit, 2 Nov 2026): won, new leads, reached, first response.
  const kpis = [
    {
      key: "won",
      label: days === 0 ? "Won" : `Won in ${days} days`,
      value: String(won),
    },
    {
      key: "new",
      label: "New leads",
      value: String(report.first_connect.entered),
    },
    {
      key: "reached",
      label: "Reached",
      value: percent(report.first_connect.rate),
    },
    {
      key: "first",
      label: "First response",
      value: minutesText(report.first_connect_minutes),
    },
  ];
  const conversions = [report.first_connect, ...report.conversions];
  const history = report.history_leads ?? 0;
  const campaigns = report.campaigns ?? [];
  const cities = report.cities ?? [];

  return (
    <div className={styles.dashboard}>
      {head}
      {report.mine ? <p className={styles.hint}>Your own leads.</p> : null}
      {days === 0 && history > 0 ? (
        <p className={styles.hint}>
          Includes {history} old lead{history === 1 ? "" : "s"} brought in as
          history.
        </p>
      ) : null}
      <section className={styles.kpis} aria-label="Outcomes">
        {kpis.map((item) => (
          <div key={item.key} className={styles.kpi}>
            <span className={styles.kpiValue}>{item.value}</span>
            <span className={styles.kpiLabel}>{item.label}</span>
          </div>
        ))}
      </section>

      {campaigns.length ? <Campaigns rows={campaigns} /> : null}
      {!report.mine ? <Salespeople rows={report.sellers} /> : null}
      {!report.mine ? <CallQuality days={days} /> : null}

      <details className={`${styles.fold} ${styles.seeMore}`}>
        <summary>See more</summary>
        <div className={styles.moreGrid}>
          <section className={styles.panel} aria-label="Work now">
            <h3>Being worked now</h3>
            <ul className={styles.tableRows}>
              <li>
                <span className={styles.rowName}>
                  {report.groups.active ?? 0} being worked
                </span>
                <span data-tone={report.overdue ? "bad" : undefined}>
                  {report.overdue} late follow-up
                  {report.overdue === 1 ? "" : "s"}
                </span>
                <span data-tone={report.no_next ? "warn" : undefined}>
                  {report.no_next} with no next step
                </span>
              </li>
            </ul>
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
            <h3>
              How leads move on
              {days === 0 ? ", all time" : `, last ${days} days`}
            </h3>
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
                      {item.key === "meeting_to_held" &&
                      report.show_rate !== null
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

          {cities.length ? (
            <section className={styles.panel} aria-label="Top cities">
              <h3>
                Most leads come from {cities[0].label}: {cities[0].count}
              </h3>
              <Bars
                label="Leads by city"
                items={cities.map((city) => ({
                  key: city.label,
                  label: city.label,
                  count: city.count,
                }))}
              />
              {report.cities_unplaced ? (
                <p className={styles.hint}>
                  {report.cities_unplaced} lead
                  {report.cities_unplaced === 1 ? " has" : "s have"} a city we
                  couldn&rsquo;t place.
                </p>
              ) : null}
            </section>
          ) : null}
        </div>
      </details>
    </div>
  );
}
