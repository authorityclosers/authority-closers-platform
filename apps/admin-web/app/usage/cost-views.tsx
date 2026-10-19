/**
 * Usage & cost views (owner order, 19 Oct 2026): one Admin shows what Sales
 * X-Ray costs and earns in production, staging and dev. Server-rendered from
 * one read; every rupee is a list-price estimate from the price sheet.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { Coins, Gauge, GitCompare, Landmark, Receipt, X } from "lucide-react";

import {
  ENVIRONMENTS,
  CALL_SORTS,
  ENVIRONMENT_LABEL,
  KIND_LABEL,
  STAGE_LABEL,
  chartSeries,
  chartsFrom,
  comparePair,
  correlation,
  costQuery,
  count,
  dayLabel,
  inr,
  minutes,
  pct,
  perMin,
  seconds,
  seriesValue,
  stamp,
  toggleChart,
  together,
  tokens,
  zeroReason,
  type CallRow,
  type ChartView,
  type Metrics,
  type Pipeline,
  type Series,
} from "@/app/usage/cost-data";
import styles from "@/app/usage/usage.module.css";
import {
  Badge,
  Button,
  Empty,
  Kpi,
  Meter,
  Panel,
  Spark,
  Table,
  Tiles,
  Why,
} from "@/app/ui/kit";

export type CostFilter = {
  tab: string;
  days: string;
  env: string;
  tests: boolean;
} & ChartView;

export const COST_WINDOWS = [
  { key: "1", label: "Today" },
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
];

export function Env({ name }: { name: string }) {
  return (
    <span className={styles.env} data-env={name}>
      {ENVIRONMENT_LABEL[name] ?? name}
    </span>
  );
}

function Chips({
  label,
  items,
}: {
  label: string;
  items: { key: string; label: ReactNode; href: string; on: boolean }[];
}) {
  return (
    <nav className={styles.chips} aria-label={label}>
      <span>{label}</span>
      {items.map((item) => (
        <Link
          key={item.key}
          href={item.href}
          scroll={false}
          className={styles.chip}
          aria-current={item.on ? "page" : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

/** Where, when and which calls. Product events only take the window. */
export function CostFilters({
  current,
  whenOnly = false,
}: {
  current: CostFilter;
  whenOnly?: boolean;
}) {
  const when = (
    <Chips
      label="When"
      items={COST_WINDOWS.map((item) => ({
        key: item.key,
        label: item.label,
        href: costQuery(current, { days: item.key }),
        on: current.days === item.key,
      }))}
    />
  );
  if (whenOnly) return <div className={styles.filters}>{when}</div>;
  return (
    <div className={styles.filters}>
      <Chips
        label="Where"
        items={["all", ...ENVIRONMENTS].map((key) => ({
          key,
          label: key === "all" ? "All" : <Env name={key} />,
          href: costQuery(current, { env: key }),
          on: current.env === key,
        }))}
      />
      {when}
      <Chips
        label="Calls"
        items={[
          {
            key: "real",
            label: "Real only",
            href: costQuery(current, { tests: false }),
            on: !current.tests,
          },
          {
            key: "tests",
            label: "With test runs",
            href: costQuery(current, { tests: true }),
            on: current.tests,
          },
        ]}
      />
    </div>
  );
}

const PROBLEM: Record<string, string> = {
  not_configured: "the metrics store isn't set up for this Admin",
  unreadable: "its last export couldn't be read",
  unknown_schema: "its export is from another version",
  too_large: "its export is too large to read",
};

export function Sources({ metrics }: { metrics: Metrics }) {
  const byEnv = new Map(
    metrics.sources.map((item) => [item.environment, item]),
  );
  return (
    <div className={styles.sources} role="group" aria-label="Data sources">
      {ENVIRONMENTS.map((name) => {
        const source = byEnv.get(name);
        const problem = metrics.problems.find(
          (item) => item.environment === name || item.environment === "all",
        );
        return (
          <span key={name}>
            <Env name={name} />{" "}
            {source ? (
              <>
                <strong>updated {stamp(source.generatedAt)}</strong>
                {source.stale ? (
                  <>
                    {" "}
                    <Badge tone="warn">late</Badge>
                  </>
                ) : null}
              </>
            ) : problem ? (
              (PROBLEM[problem.problem] ?? problem.problem)
            ) : (
              "not shown in this Admin"
            )}
          </span>
        );
      })}
      <Why detail="Every 15 minutes each environment exports usage numbers only (no call content) into a separate metrics store, read-only. Rupees are list prices from the price sheet (₹100 per US dollar), not invoices. Calls copied from one database to another count once, in the environment they ran in. Days are India time." />
    </div>
  );
}

/* ---------- Overview ---------- */

function DailyBars({ metrics }: { metrics: Metrics }) {
  const days = metrics.overview.daily;
  const peak = Math.max(0.01, ...days.map((day) => day.spend));
  if (!days.length) return null;
  return (
    <>
      <div
        className={styles.bars}
        role="img"
        aria-label="Spend per day by environment"
      >
        {days.map((day) => (
          <span
            key={day.day}
            className={styles.bar}
            data-empty={day.spend ? undefined : ""}
            title={`${dayLabel(day.day)}: ${inr(day.spend)} · ${minutes(day.audioMinutes)} of audio · ${count(day.calls)} calls`}
          >
            {ENVIRONMENTS.filter((name) => day.byEnvironment[name]).map(
              (name) => (
                <i
                  key={name}
                  data-env={name}
                  style={{
                    height: `${((day.byEnvironment[name] ?? 0) / peak) * 100}%`,
                  }}
                />
              ),
            )}
          </span>
        ))}
      </div>
      <div className={styles.axis} aria-hidden="true">
        <span>{dayLabel(days[0]?.day ?? "")}</span>
        <span>peak {inr(peak)}</span>
        <span>{dayLabel(days.at(-1)?.day ?? "")}</span>
      </div>
    </>
  );
}

function PerMinuteBars({ metrics }: { metrics: Metrics }) {
  const days = metrics.overview.daily;
  const values = days.map((day) => day.perMinute ?? 0);
  const peak = Math.max(0.01, ...values);
  if (!days.length) return null;
  return (
    <>
      <div
        className={styles.bars}
        role="img"
        aria-label="Rupees per audio minute per day"
      >
        {days.map((day) => (
          <span
            key={day.day}
            className={styles.bar}
            data-empty={day.perMinute ? undefined : ""}
            title={`${dayLabel(day.day)}: ${perMin(day.perMinute)} over ${minutes(day.audioMinutes)}`}
          >
            {day.perMinute ? (
              <i style={{ height: `${(day.perMinute / peak) * 100}%` }} />
            ) : null}
          </span>
        ))}
      </div>
      <div className={styles.axis} aria-hidden="true">
        <span>{dayLabel(days[0]?.day ?? "")}</span>
        <span>highest {perMin(peak)}</span>
        <span>{dayLabel(days.at(-1)?.day ?? "")}</span>
      </div>
    </>
  );
}

export function OverviewView({
  metrics,
  current,
}: {
  metrics: Metrics;
  current: CostFilter;
}) {
  const o = metrics.overview;
  const ideas = metrics.ideas;
  const scope = current.tests ? "all runs" : "real calls";
  const windowLabel =
    COST_WINDOWS.find((item) => item.key === current.days)?.label ??
    `${metrics.days} days`;
  return (
    <>
      <Tiles label="Spend">
        <Kpi
          label="Spent this month"
          value={inr(o.spendMonth)}
          note={`Today ${inr(o.spendToday)} · ${scope}`}
          spark={
            <Spark
              values={o.daily.map((day) => day.spend)}
              label="Spend per day"
            />
          }
        />
        <Kpi
          label="Cost per audio minute"
          value={perMin(o.perMinute)}
          note={`${minutes(o.audioMinutes)} transcribed · ${windowLabel}`}
          spark={
            <Spark
              values={o.daily.map((day) => day.perMinute ?? 0)}
              label="Cost per audio minute per day"
            />
          }
        />
        <Kpi
          label="Calls analysed"
          value={count(o.calls)}
          note={`${count(o.reports)} reports · ${inr(ideas.perReport)} per report`}
        />
        <Kpi
          label="Test runs"
          value={count(o.testRuns)}
          tone={o.testsWindow > o.spendWindow ? "warn" : undefined}
          note={`${inr(o.testsWindow)} on canaries and QA · ${windowLabel}`}
        />
      </Tiles>
      <Panel
        title="By environment"
        sub={windowLabel}
        tools={
          <Why detail="Each environment's own spend. Today and this month are India time. Upload to report is the median from the upload to the report being ready." />
        }
      >
        <Table
          label="Spend by environment"
          cards={o.environments.map((row) => (
            <div key={row.environment} role="listitem">
              <Env name={row.environment} /> · {inr(row.window)} ·{" "}
              {perMin(row.perMinute)} · {count(row.calls)} calls
            </div>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Environment</th>
              <th scope="col" data-num="">
                Today
              </th>
              <th scope="col" data-num="">
                This month
              </th>
              <th scope="col" data-num="">
                {windowLabel}
              </th>
              <th scope="col" data-num="">
                Per audio min
              </th>
              <th scope="col" data-num="">
                Calls
              </th>
              <th scope="col" data-num="">
                Reports
              </th>
              <th scope="col" data-num="">
                Minutes billed
              </th>
              <th scope="col" data-num="">
                Upload to report
              </th>
              <th scope="col" data-num="">
                Test runs
              </th>
            </tr>
          </thead>
          <tbody>
            {o.environments.map((row) => (
              <tr key={row.environment}>
                <th scope="row">
                  <Env name={row.environment} />
                </th>
                <td data-num="">{inr(row.today)}</td>
                <td data-num="">{inr(row.month)}</td>
                <td data-num="">{inr(row.window)}</td>
                <td data-num="">{perMin(row.perMinute)}</td>
                <td data-num="">{count(row.calls)}</td>
                <td data-num="">{count(row.reports)}</td>
                <td data-num="">{minutes(row.billedMinutes)}</td>
                <td data-num="">{seconds(row.reportP50)}</td>
                <td data-num="">
                  {count(row.testRuns)}
                  <span className={styles.sub}>{inr(row.tests)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
      <ChartBoard
        metrics={metrics}
        current={current}
        windowLabel={windowLabel}
      />
      <div className={styles.columns}>
        <Panel
          title="Where the money goes"
          sub={`${inr(o.spendWindow)} · ${scope}`}
          tools={
            <Why detail="Spend per pipeline step. Audio check runs on our own server and costs nothing." />
          }
        >
          {o.byStage.length ? (
            o.byStage.map((row) => (
              <div key={row.stage} className={styles.share}>
                <span>{row.label}</span>
                <Meter
                  value={row.share}
                  max={1}
                  label={`${pct(row.share)} of spend`}
                />
                <strong>{inr(row.rupees)}</strong>
                <small>{perMin(row.perMinute)}</small>
              </div>
            ))
          ) : (
            <Empty icon={Coins} title="Nothing spent in this window" />
          )}
        </Panel>
        <Panel
          title="Worth knowing"
          tools={
            <Why detail="Money spent where it bought nothing a customer saw, so it can be cut." />
          }
        >
          <dl className={styles.facts}>
            <div>
              <dt>Calls with no report</dt>
              <dd>
                {inr(ideas.noReportRupees)}
                <small>{count(ideas.noReportCalls)} calls</small>
              </dd>
            </div>
            <div>
              <dt>Transcribed again</dt>
              <dd>
                {inr(ideas.repeatRupees)}
                <small>{count(ideas.repeatTranscriptions)} repeats</small>
              </dd>
            </div>
            <div>
              <dt>Share spent on test runs</dt>
              <dd>
                {pct(ideas.testsShare)}
                <small>of all spend in the window</small>
              </dd>
            </div>
            <div>
              <dt>Upload to report</dt>
              <dd>
                {seconds(o.reportP50)}
                <small>median · slowest tenth {seconds(o.reportP90)}</small>
              </dd>
            </div>
          </dl>
        </Panel>
      </div>
      <div className={styles.columns}>
        <Panel title="Top spenders" sub="companies">
          {ideas.topCompanies.length ? (
            <Table label="Top spending companies">
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col" data-num="">
                    Calls
                  </th>
                  <th scope="col" data-num="">
                    Per call
                  </th>
                  <th scope="col" data-num="">
                    Spend
                  </th>
                </tr>
              </thead>
              <tbody>
                {ideas.topCompanies.map((row) => (
                  <tr key={`${row.environment}-${row.company}`}>
                    <th scope="row">
                      {row.company}
                      <span className={styles.sub}>
                        <Env name={row.environment} />
                      </span>
                    </th>
                    <td data-num="">{count(row.calls)}</td>
                    <td data-num="">{inr(row.perCall)}</td>
                    <td data-num="">{inr(row.rupees)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <Empty
              icon={Landmark}
              title="No company spent anything in this window"
            />
          )}
        </Panel>
        <Panel title="Still missing" sub="next to measure">
          <ul className={styles.missing}>
            {ideas.missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
            {o.unpricedSteps ? (
              <li>
                {count(o.unpricedSteps)} finished steps have no price on the
                price sheet yet.
              </li>
            ) : null}
          </ul>
        </Panel>
      </div>
    </>
  );
}

/* ---------- Charts: pick which show, compare two (owner, 19 Oct 2026) ---------- */

/** Any per-day series as bars, each day's value against the window's highest. */
function SeriesBars({ series }: { series: Series }) {
  const peak = Math.max(0, ...series.values.map((value) => value ?? 0));
  if (!series.days.length || peak <= 0)
    return <Empty icon={Coins} title="Nothing to draw in this window" />;
  const environment = series.key.startsWith("env-")
    ? series.key.slice(4)
    : undefined;
  return (
    <>
      <div className={styles.bars} role="img" aria-label={series.label}>
        {series.days.map((day, index) => {
          const value = series.values[index] ?? null;
          return (
            <span
              key={day}
              className={styles.bar}
              data-empty={value ? undefined : ""}
              title={`${dayLabel(day)}: ${seriesValue(series.unit, value)}`}
            >
              {value ? (
                <i
                  data-env={environment}
                  style={{ height: `${(value / peak) * 100}%` }}
                />
              ) : null}
            </span>
          );
        })}
      </div>
      <div className={styles.axis} aria-hidden="true">
        <span>{dayLabel(series.days[0] ?? "")}</span>
        <span>highest {seriesValue(series.unit, peak)}</span>
        <span>{dayLabel(series.days.at(-1) ?? "")}</span>
      </div>
    </>
  );
}

const LINE_W = 640;
const LINE_H = 180;
const LINE_PAD = 8;

const peakOf = (series: Series) =>
  Math.max(0, ...series.values.map((value) => value ?? 0));

/** The polyline for one series, drawn against its own highest value. */
function linePoints(series: Series): string {
  const peak = peakOf(series) || 1;
  const step =
    series.values.length > 1
      ? (LINE_W - 2 * LINE_PAD) / (series.values.length - 1)
      : 0;
  return series.values
    .map((value, index) =>
      value === null
        ? null
        : `${(LINE_PAD + index * step).toFixed(1)},${(
            LINE_H -
            LINE_PAD -
            (value / peak) * (LINE_H - 2 * LINE_PAD)
          ).toFixed(1)}`,
    )
    .filter((point): point is string => point !== null)
    .join(" ");
}

/** Two series over the same days, each on its own scale, with a day-by-day table. */
function CompareChart({ a, b }: { a: Series; b: Series }) {
  const r = correlation(a.values, b.values);
  const total = (series: Series) =>
    series.unit === "perMin"
      ? null
      : series.values.reduce<number>((sum, value) => sum + (value ?? 0), 0);
  return (
    <Panel
      title={`${a.label} and ${b.label}`}
      sub={`each on its own scale · they ${together(r)}`}
      tools={
        <Why detail="Both lines share the days; each is drawn against its own highest value, so their shapes compare even when the units differ. They move together when the correlation over the days both have is 0.6 or more." />
      }
    >
      <svg
        className={styles.lines}
        viewBox={`0 0 ${LINE_W} ${LINE_H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${a.label} compared with ${b.label}, day by day`}
      >
        <polyline className={styles.lineA} points={linePoints(a)} />
        <polyline className={styles.lineB} points={linePoints(b)} />
      </svg>
      <div className={styles.axis} aria-hidden="true">
        <span>{dayLabel(a.days[0] ?? "")}</span>
        <span>{dayLabel(a.days.at(-1) ?? "")}</span>
      </div>
      <div className={styles.compareLegend}>
        {[a, b].map((series, index) => {
          const sum = total(series);
          return (
            <span key={series.key} data-line={index ? "b" : "a"}>
              <strong>{series.label}</strong> highest{" "}
              {seriesValue(series.unit, peakOf(series))}
              {sum !== null ? ` · total ${seriesValue(series.unit, sum)}` : ""}
            </span>
          );
        })}
      </div>
      <details className={styles.compareDays}>
        <summary>Day by day</summary>
        <Table label={`${a.label} and ${b.label} by day`}>
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col" data-num="">
                {a.label}
              </th>
              <th scope="col" data-num="">
                {b.label}
              </th>
            </tr>
          </thead>
          <tbody>
            {a.days.map((day, index) => (
              <tr key={day}>
                <th scope="row">{dayLabel(day)}</th>
                <td data-num="">
                  {seriesValue(a.unit, a.values[index] ?? null)}
                </td>
                <td data-num="">
                  {seriesValue(b.unit, b.values[index] ?? null)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </details>
    </Panel>
  );
}

/** The Overview's charts: a picker, an optional comparison, then the chosen charts. */
export function ChartBoard({
  metrics,
  current,
  windowLabel,
}: {
  metrics: Metrics;
  current: CostFilter;
  windowLabel: string;
}) {
  const o = metrics.overview;
  const series = chartSeries(metrics);
  const byKey = new Map(series.map((item) => [item.key, item]));
  const shown = chartsFrom(current.charts, [...byKey.keys()]);
  const a = current.ca ? byKey.get(current.ca) : undefined;
  const b = current.cb ? byKey.get(current.cb) : undefined;
  const comparing = a && b && a.key !== b.key ? { a, b } : null;
  const link = (change: ChartView) => costQuery(current, change);
  const options = series.map((item) => (
    <option key={item.key} value={item.key}>
      {item.label}
    </option>
  ));
  return (
    <>
      <div className={styles.chartTools}>
        <Chips
          label="Charts"
          items={series.map((item) => ({
            key: item.key,
            label: item.label,
            href: link({ charts: toggleChart(shown, item.key) }),
            on: shown.includes(item.key),
          }))}
        />
        <form
          className={styles.compareForm}
          action="/usage"
          method="get"
          aria-label="Compare two charts"
        >
          {current.days !== "30" ? (
            <input type="hidden" name="days" value={current.days} />
          ) : null}
          {current.env !== "all" ? (
            <input type="hidden" name="env" value={current.env} />
          ) : null}
          {current.tests ? (
            <input type="hidden" name="tests" value="1" />
          ) : null}
          {current.charts ? (
            <input type="hidden" name="charts" value={current.charts} />
          ) : null}
          <label>
            <span>Compare</span>
            <select name="ca" defaultValue={comparing?.a.key ?? "spend"}>
              {options}
            </select>
          </label>
          <label>
            <span>with</span>
            <select name="cb" defaultValue={comparing?.b.key ?? "perMinute"}>
              {options}
            </select>
          </label>
          <Button type="submit">Compare</Button>
          {comparing ? (
            <Link
              href={link({ ca: undefined, cb: undefined })}
              scroll={false}
              className={styles.chip}
            >
              Stop comparing
            </Link>
          ) : null}
        </form>
      </div>
      {comparing ? <CompareChart a={comparing.a} b={comparing.b} /> : null}
      {shown.length ? (
        <div className={styles.columns}>
          {shown.map((key) => {
            const item = byKey.get(key);
            if (!item) return null;
            return (
              <Panel
                key={key}
                title={item.label}
                sub={key === "perMinute" ? "per day" : windowLabel}
                tools={
                  <span className={styles.legend}>
                    {key === "spend"
                      ? ENVIRONMENTS.map((name) => (
                          <Env key={name} name={name} />
                        ))
                      : null}
                    {key === "perMinute" ? (
                      <Why detail="Each call's whole cost (transcription, facts, report, pointer review, repeats) on the day it was first transcribed, divided by its minutes of audio. A later backfill counts on the call's own day." />
                    ) : null}
                    <Link
                      href={link({ charts: toggleChart(shown, key) })}
                      scroll={false}
                      className={styles.hide}
                      aria-label={`Hide ${item.label}`}
                      title="Hide this chart"
                    >
                      <X size={14} aria-hidden />
                    </Link>
                  </span>
                }
              >
                {key === "spend" ? (
                  o.spendWindow > 0 ? (
                    <DailyBars metrics={metrics} />
                  ) : (
                    <Empty icon={Coins} title="No spend in this window" />
                  )
                ) : key === "perMinute" ? (
                  o.audioMinutes > 0 ? (
                    <PerMinuteBars metrics={metrics} />
                  ) : (
                    <Empty
                      icon={Gauge}
                      title="No audio transcribed in this window"
                    />
                  )
                ) : (
                  <SeriesBars series={item} />
                )}
              </Panel>
            );
          })}
        </div>
      ) : (
        <p className={styles.hint}>All charts are hidden. Pick any above.</p>
      )}
    </>
  );
}

/* ---------- Per call ---------- */

const STAGE_ORDER = ["C2", "C4", "C5", "PR"];

const STEP_STATUS: Record<string, string> = {
  succeeded: "done",
  dead_letter: "failed",
  retry_wait: "retrying",
  leased: "running",
  queued: "waiting",
  cancelled: "cancelled",
};

/** Each provider step of one call: what ran, how, and what it cost. */
function CallSteps({ row }: { row: CallRow }) {
  if (!row.steps.length)
    return <p className={styles.hint}>This read has no step detail.</p>;
  return (
    <Table label={`Steps of the ${row.company} call at ${stamp(row.at)}`}>
      <thead>
        <tr>
          <th scope="col">Step</th>
          <th scope="col">Provider and model</th>
          <th scope="col">Status</th>
          <th scope="col" data-num="">
            Tries
          </th>
          <th scope="col" data-num="">
            Tokens in
          </th>
          <th scope="col" data-num="">
            Tokens out
          </th>
          <th scope="col" data-num="">
            Audio
          </th>
          <th scope="col" data-num="">
            Took
          </th>
          <th scope="col" data-num="">
            Cost
          </th>
        </tr>
      </thead>
      <tbody>
        {row.steps.map((step, index) => (
          <tr key={`${step.stage}-${step.at}-${index}`}>
            <th scope="row">
              {STAGE_LABEL[step.stage] ?? step.stage}
              <span className={styles.sub}>{stamp(step.at)}</span>
            </th>
            <td>
              {step.provider ?? "–"}
              <span className={styles.sub}>{step.model ?? "–"}</span>
            </td>
            <td>{STEP_STATUS[step.status] ?? step.status}</td>
            <td data-num="">{count(step.attempts)}</td>
            <td data-num="">{tokens(step.inputTokens)}</td>
            <td data-num="">{tokens(step.outputTokens)}</td>
            <td data-num="">
              {step.audioMinutes === null ? "–" : minutes(step.audioMinutes)}
            </td>
            <td data-num="">{seconds(step.elapsedMs)}</td>
            <td data-num="">
              {step.rupees === null ? (
                <span className={styles.sub}>no price</span>
              ) : (
                inr(step.rupees)
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

/** One call: a summary line that opens to its steps. */
function CallLine({ row, here }: { row: CallRow; here: string | null }) {
  return (
    <details className={styles.callLine} role="listitem">
      <summary>
        <span className={styles.callWho}>
          <strong>{row.company}</strong>
          <span className={styles.sub}>
            <Env name={row.environment} /> · {stamp(row.at)} ·{" "}
            {minutes(row.audioMinutes)}
            {row.kind !== "real"
              ? ` · ${KIND_LABEL[row.kind] ?? row.kind}`
              : ""}
          </span>
          {row.models.length ? (
            <span className={styles.sub}>{row.models.join(" · ")}</span>
          ) : null}
        </span>
        {STAGE_ORDER.map((stage) => {
          const cost = row.stages[stage];
          return (
            <span key={stage} data-num="" data-label={STAGE_LABEL[stage]}>
              {cost ? inr(cost.rupees) : "–"}
              {cost && cost.runs > 1 ? <small>{cost.runs} runs</small> : null}
              {cost && cost.failed ? <small>{cost.failed} failed</small> : null}
            </span>
          );
        })}
        <span data-num="" data-label="Total">
          <strong>{inr(row.rupees)}</strong>
          <small>{perMin(row.perMinute)}</small>
        </span>
        <span data-num="" data-label="Tokens">
          {tokens(row.tokens)}
        </span>
        <span data-num="" data-label="Report in">
          {row.report ? seconds(row.reportMs) : "no report"}
        </span>
      </summary>
      <div className={styles.callDetail}>
        <CallSteps row={row} />
        <p className={styles.hint}>
          {minutes(row.billedMinutes)} billed ·{" "}
          {row.margin === null
            ? "no paid plan, so no margin"
            : `margin ${inr(row.margin)}`}
          {row.version ? ` · ${row.version}` : ""}
          {here === row.environment ? (
            <>
              {" · "}
              <Link href={`/calls/${row.id}`}>Open the call</Link>
            </>
          ) : null}
        </p>
      </div>
    </details>
  );
}

export function CallsView({
  metrics,
  current,
}: {
  metrics: Metrics;
  current: CostFilter;
}) {
  const { rows, total, sort, zeroRows, zeroTotal } = metrics.calls;
  const sorter = (
    <div className={styles.filters}>
      <Chips
        label="Sort"
        items={CALL_SORTS.map((item) => ({
          key: item.key,
          label: item.label,
          href: costQuery(current, {
            sort: item.key === "newest" ? undefined : item.key,
          }),
          on: sort === item.key,
        }))}
      />
    </div>
  );
  if (!rows.length && !zeroTotal)
    return (
      <Panel title="Calls">
        <Empty
          icon={Receipt}
          title="No calls in this window"
          text="Calls show here once a provider step has run for them."
        />
      </Panel>
    );
  return (
    <>
      {sorter}
      <Panel
        title="Cost per call"
        sub={
          total > rows.length
            ? `${count(rows.length)} of ${count(total)} calls with a cost`
            : `${count(total)} ${total === 1 ? "call" : "calls"} with a cost`
        }
        tools={
          <Why detail="Each call's provider steps priced from the price sheet: transcription by audio length, facts, report and pointer review by tokens in and out. Open a call to see every step: provider and model, tries, tokens, audio, time and cost. Margin needs a paid plan. Calls that cost nothing are listed apart below." />
        }
      >
        {rows.length ? (
          <div className={styles.callList} role="list" aria-label="Calls">
            <div className={styles.callHead} aria-hidden="true">
              <span>Call</span>
              {STAGE_ORDER.map((stage) => (
                <span key={stage} data-num="">
                  {STAGE_LABEL[stage]}
                </span>
              ))}
              <span data-num="">Total</span>
              <span data-num="">Tokens</span>
              <span data-num="">Report in</span>
            </div>
            {rows.map((row) => (
              <CallLine
                key={`${row.environment}-${row.id}`}
                row={row}
                here={metrics.here}
              />
            ))}
          </div>
        ) : (
          <Empty icon={Receipt} title="No call cost anything in this window" />
        )}
      </Panel>
      {zeroTotal ? (
        <details className={styles.zeroCalls}>
          <summary>
            {count(zeroTotal)} {zeroTotal === 1 ? "call" : "calls"} cost nothing{" "}
            <span className={styles.sub}>no paid step finished · show</span>
          </summary>
          <ul>
            {zeroRows.map((row) => (
              <li key={`${row.environment}-${row.id}`}>
                <strong>{row.company}</strong>{" "}
                <span className={styles.sub}>
                  <Env name={row.environment} /> · {stamp(row.at)} ·{" "}
                  {minutes(row.audioMinutes)} · {zeroReason(row.statuses)}
                </span>
              </li>
            ))}
          </ul>
          {zeroTotal > zeroRows.length ? (
            <p className={styles.hint}>
              Newest {count(zeroRows.length)} shown.
            </p>
          ) : null}
        </details>
      ) : null}
    </>
  );
}

/* ---------- Revenue against cost ---------- */

export function RevenueView({ metrics }: { metrics: Metrics }) {
  const revenue = metrics.revenue;
  const totals = ENVIRONMENTS.filter((name) => revenue.totals[name]);
  return (
    <>
      <Tiles label="Revenue against cost">
        {totals.map((name) => {
          const value = revenue.totals[name] ?? {
            revenue: 0,
            cost: 0,
            margin: 0,
          };
          return (
            <Kpi
              key={name}
              label={`${ENVIRONMENT_LABEL[name]} margin`}
              value={inr(value.margin)}
              tone={value.margin >= 0 ? "good" : "bad"}
              note={`${inr(value.revenue)} revenue · ${inr(value.cost)} cost`}
            />
          );
        })}
      </Tiles>
      <Panel
        title="Revenue against internal cost"
        sub="per company"
        tools={
          <Why detail="Revenue is money received in this window: captured payments and subscription charges in live mode, minus refunds, read from the billing tables. Nothing here changes billing. Cost is the list-price cost of that company's calls. Staging and dev payments are test money." />
        }
      >
        {revenue.paymentsRecorded === 0 && revenue.plansRecorded === 0 ? (
          <p className={styles.note}>
            No payments or plans are recorded in any environment yet, so every
            company shows cost only. Revenue fills in from the first paid plan.
          </p>
        ) : null}
        {revenue.rows.length ? (
          <Table label="Revenue and cost per company">
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Plan</th>
                <th scope="col" data-num="">
                  Revenue
                </th>
                <th scope="col" data-num="">
                  Cost
                </th>
                <th scope="col" data-num="">
                  Margin
                </th>
                <th scope="col" data-num="">
                  Calls
                </th>
                <th scope="col" data-num="">
                  Minutes billed
                </th>
                <th scope="col" data-num="">
                  Cost per billed min
                </th>
              </tr>
            </thead>
            <tbody>
              {revenue.rows.map((row) => (
                <tr key={`${row.environment}-${row.company}`}>
                  <th scope="row">
                    {row.company}
                    <span className={styles.sub}>
                      <Env name={row.environment} /> · {row.companyKind}
                    </span>
                  </th>
                  <td>
                    {row.plan ? (
                      <>
                        {row.plan.name ?? "Plan"}
                        <span className={styles.sub}>
                          {inr(row.plan.rupees)}/{row.plan.interval ?? "period"}{" "}
                          · {count(row.plan.includedMinutes)} min
                          {row.plan.mode === "test" ? " · test" : ""}
                        </span>
                      </>
                    ) : (
                      <span className={styles.sub}>none</span>
                    )}
                  </td>
                  <td data-num="">
                    {inr(row.revenue)}
                    {row.testRevenue ? (
                      <span className={styles.sub}>
                        +{inr(row.testRevenue)} test
                      </span>
                    ) : null}
                  </td>
                  <td data-num="">{inr(row.cost)}</td>
                  <td data-num="">
                    <span
                      className={row.margin >= 0 ? styles.better : styles.worse}
                    >
                      {inr(row.margin)}
                    </span>
                  </td>
                  <td data-num="">{count(row.calls)}</td>
                  <td data-num="">{minutes(row.billedMinutes)}</td>
                  <td data-num="">{inr(row.costPerBilledMinute)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <Empty icon={Landmark} title="No revenue or cost in this window" />
        )}
      </Panel>
    </>
  );
}

/* ---------- Providers ---------- */

export function ProvidersView({ metrics }: { metrics: Metrics }) {
  const { models, daily } = metrics.providers;
  return (
    <>
      <Panel
        title="Providers and models"
        sub="tokens, audio and cost"
        tools={
          <Why detail="Tokens in and out are the provider's own counters from each step's receipt (Gemini thinking tokens count as output). Audio minutes are what was sent for transcription." />
        }
      >
        {models.length ? (
          <Table label="Providers and models">
            <thead>
              <tr>
                <th scope="col">Provider · model</th>
                <th scope="col">Steps</th>
                <th scope="col" data-num="">
                  Calls
                </th>
                <th scope="col" data-num="">
                  Tokens in
                </th>
                <th scope="col" data-num="">
                  Tokens out
                </th>
                <th scope="col" data-num="">
                  Audio
                </th>
                <th scope="col" data-num="">
                  Failed
                </th>
                <th scope="col" data-num="">
                  Cost
                </th>
                <th scope="col">Share</th>
              </tr>
            </thead>
            <tbody>
              {models.map((row) => (
                <tr key={`${row.provider}-${row.model}`}>
                  <th scope="row">
                    {row.provider}
                    <span className={styles.sub}>{row.model}</span>
                  </th>
                  <td>
                    {row.stages
                      .map((stage) => STAGE_LABEL[stage] ?? stage)
                      .join(", ")}
                  </td>
                  <td data-num="">{count(row.calls)}</td>
                  <td data-num="">{tokens(row.inputTokens)}</td>
                  <td data-num="">{tokens(row.outputTokens)}</td>
                  <td data-num="">
                    {row.audioMinutes ? minutes(row.audioMinutes) : "–"}
                  </td>
                  <td data-num="">{count(row.failed)}</td>
                  <td data-num="">{inr(row.rupees)}</td>
                  <td>
                    <Meter
                      value={row.share}
                      max={1}
                      label={`${pct(row.share)} of spend`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <Empty icon={Coins} title="No provider work in this window" />
        )}
      </Panel>
      <Panel title="Per day" sub="India time, newest first">
        {daily.length ? (
          <Table label="Provider use per day">
            <thead>
              <tr>
                <th scope="col">Day</th>
                <th scope="col">Provider · model</th>
                <th scope="col" data-num="">
                  Tokens in
                </th>
                <th scope="col" data-num="">
                  Tokens out
                </th>
                <th scope="col" data-num="">
                  Audio
                </th>
                <th scope="col" data-num="">
                  Cost
                </th>
              </tr>
            </thead>
            <tbody>
              {daily.map((row) => (
                <tr key={`${row.day}-${row.provider}-${row.model}`}>
                  <th scope="row">{dayLabel(row.day)}</th>
                  <td>
                    {row.provider} ·{" "}
                    <span className={styles.mono}>{row.model}</span>
                  </td>
                  <td data-num="">{tokens(row.inputTokens)}</td>
                  <td data-num="">{tokens(row.outputTokens)}</td>
                  <td data-num="">
                    {row.audioMinutes ? minutes(row.audioMinutes) : "–"}
                  </td>
                  <td data-num="">{inr(row.rupees)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <Empty icon={Coins} title="No provider work in this window" />
        )}
      </Panel>
    </>
  );
}

/* ---------- Pipelines ---------- */

type Measure = {
  label: string;
  value: (item: Pipeline) => number | null;
  show: (value: number | null) => string;
  lowerIsBetter?: boolean;
};

const MEASURES: Measure[] = [
  {
    label: "Calls",
    value: (p) => p.calls,
    show: (v) => (v === null ? "–" : count(v)),
  },
  {
    label: "Test runs",
    value: (p) => p.testRuns,
    show: (v) => (v === null ? "–" : count(v)),
  },
  {
    label: "Cost per audio minute",
    value: (p) => p.perMinute,
    show: perMin,
    lowerIsBetter: true,
  },
  {
    label: "Failed steps",
    value: (p) => p.failureRate,
    show: pct,
    lowerIsBetter: true,
  },
  {
    label: "Retried steps",
    value: (p) => p.retryRate,
    show: pct,
    lowerIsBetter: true,
  },
  {
    label: "Audio check",
    value: (p) => p.stageMs.C1 ?? null,
    show: seconds,
    lowerIsBetter: true,
  },
  {
    label: "Transcription",
    value: (p) => p.stageMs.C2 ?? null,
    show: seconds,
    lowerIsBetter: true,
  },
  {
    label: "Facts",
    value: (p) => p.stageMs.C4 ?? null,
    show: seconds,
    lowerIsBetter: true,
  },
  {
    label: "Report",
    value: (p) => p.stageMs.C5 ?? null,
    show: seconds,
    lowerIsBetter: true,
  },
  {
    label: "Upload to report",
    value: (p) => p.reportP50,
    show: seconds,
    lowerIsBetter: true,
  },
  { label: "Gold agreement", value: (p) => p.gold.agreement, show: pct },
];

function verdict(measure: Measure, mine: number | null, other: number | null) {
  if (
    mine === null ||
    other === null ||
    mine === other ||
    measure.label === "Calls" ||
    measure.label === "Test runs"
  )
    return undefined;
  const better = measure.lowerIsBetter ? mine < other : mine > other;
  return better ? styles.better : styles.worse;
}

export function PipelinesView({
  metrics,
  current,
  a,
  b,
}: {
  metrics: Metrics;
  current: CostFilter;
  a?: string;
  b?: string;
}) {
  const pipelines = metrics.pipelines;
  if (!pipelines.length)
    return (
      <Panel title="Pipeline versions">
        <Empty icon={GitCompare} title="No analyses in this window" />
      </Panel>
    );
  const [first, second] = comparePair(pipelines, a, b);
  return (
    <>
      <Panel
        title="Compare two versions"
        tools={
          <Why detail="A version is the coaching prompt, facts prompt, report model and transcription model a call was analysed with. Times are medians per step. Gold agreement counts agree as 1 and partly as a half, over the gold reviews of that version's calls." />
        }
      >
        <form action="/usage" method="get" className={styles.compare}>
          <input type="hidden" name="tab" value="pipelines" />
          {current.days !== "30" ? (
            <input type="hidden" name="days" value={current.days} />
          ) : null}
          {current.env !== "all" ? (
            <input type="hidden" name="env" value={current.env} />
          ) : null}
          {current.tests ? (
            <input type="hidden" name="tests" value="1" />
          ) : null}
          <label>
            A{" "}
            <select name="a" defaultValue={first?.id}>
              {pipelines.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            B{" "}
            <select name="b" defaultValue={second?.id}>
              {pipelines.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" variant="primary">
            Compare
          </Button>
        </form>
        {first && second ? (
          <Table label="Two versions side by side">
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col" data-num="">
                  A · {first.prompt ?? "older"}
                </th>
                <th scope="col" data-num="">
                  B · {second.prompt ?? "older"}
                </th>
              </tr>
            </thead>
            <tbody>
              {MEASURES.map((measure) => {
                const one = measure.value(first);
                const two = measure.value(second);
                return (
                  <tr key={measure.label}>
                    <th scope="row">{measure.label}</th>
                    <td data-num="">
                      <span className={verdict(measure, one, two)}>
                        {measure.show(one)}
                      </span>
                    </td>
                    <td data-num="">
                      <span className={verdict(measure, two, one)}>
                        {measure.show(two)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        ) : (
          <p className={styles.note}>Only one version ran in this window.</p>
        )}
      </Panel>
      <Panel
        title="All versions"
        sub={`${count(pipelines.length)} seen, newest first`}
      >
        <Table label="Pipeline versions">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Where</th>
              <th scope="col" data-num="">
                Calls
              </th>
              <th scope="col" data-num="">
                Tests
              </th>
              <th scope="col" data-num="">
                Per audio min
              </th>
              <th scope="col" data-num="">
                Failed
              </th>
              <th scope="col" data-num="">
                Report step
              </th>
              <th scope="col" data-num="">
                Gold
              </th>
              <th scope="col" data-num="">
                Last run
              </th>
            </tr>
          </thead>
          <tbody>
            {pipelines.map((item) => (
              <tr key={item.id}>
                <th scope="row">
                  <span className={styles.mono}>{item.label}</span>
                </th>
                <td>
                  {item.environments.map((name) => (
                    <Env key={name} name={name} />
                  ))}
                </td>
                <td data-num="">{count(item.calls)}</td>
                <td data-num="">{count(item.testRuns)}</td>
                <td data-num="">{perMin(item.perMinute)}</td>
                <td data-num="">{pct(item.failureRate)}</td>
                <td data-num="">{seconds(item.stageMs.C5 ?? null)}</td>
                <td data-num="">
                  {item.gold.reviewed ? (
                    <>
                      {pct(item.gold.agreement)}
                      <span className={styles.sub}>
                        {count(item.gold.reviewed)} reviewed
                      </span>
                    </>
                  ) : (
                    <span className={styles.sub}>no gold yet</span>
                  )}
                </td>
                <td data-num="">{stamp(item.lastSeen)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
    </>
  );
}

/* ---------- Health of money ---------- */

export function MoneyView({ metrics }: { metrics: Metrics }) {
  const money = metrics.money;
  if (!money.environments.length)
    return (
      <Panel title="Budget holds">
        <Empty icon={Landmark} title="No environment's budget is shown here" />
      </Panel>
    );
  return (
    <>
      <Tiles label="AI budget">
        {money.environments.map((row) => (
          <Kpi
            key={row.environment}
            label={`${ENVIRONMENT_LABEL[row.environment] ?? row.environment} AI budget used`}
            value={pct(row.usedShare)}
            tone={
              row.waitingCalls || (row.usedShare ?? 0) >= 0.9
                ? "bad"
                : (row.usedShare ?? 0) >= 0.8
                  ? "warn"
                  : undefined
            }
            note={`${inr(row.usedRupees)} of ${inr(row.cap)}${
              row.period === "monthly"
                ? " this month"
                : row.period === "daily"
                  ? " today"
                  : ""
            } · ${count(row.open)} open holds${
              row.waitingCalls
                ? ` · ${count(row.waitingCalls)} calls waiting`
                : ""
            }`}
            href={
              row.environment === metrics.here
                ? "/sales-xray/execution"
                : undefined
            }
          />
        ))}
      </Tiles>
      <Panel
        title="Why holds stay open"
        tools={<Badge tone="good">automatic from v0.64</Badge>}
      >
        <p className={styles.note}>{money.finding}</p>
      </Panel>
      {money.environments.map((row) => (
        <Panel
          key={row.environment}
          title={`${ENVIRONMENT_LABEL[row.environment] ?? row.environment} holds`}
          sub={`${count(row.settled)} settled at list price · ${inr(row.settledRupees)}`}
          tools={
            <Why detail="A hold reserves the most a step may cost before it runs. It should settle to the real cost once the provider's receipt arrives; until then the full amount counts against the spend cap. Nothing here changes a hold." />
          }
        >
          <div className={styles.columns}>
            <Table label={`${row.environment} open holds by reason`}>
              <thead>
                <tr>
                  <th scope="col">Open because</th>
                  <th scope="col" data-num="">
                    Holds
                  </th>
                  <th scope="col" data-num="">
                    Held
                  </th>
                </tr>
              </thead>
              <tbody>
                {row.byReason.length ? (
                  row.byReason.map((reason) => (
                    <tr key={reason.ref}>
                      <th scope="row">{reason.label}</th>
                      <td data-num="">{count(reason.n)}</td>
                      <td data-num="">{inr(reason.rupees)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <th scope="row">Nothing open</th>
                    <td data-num="">0</td>
                    <td data-num="">{inr(0)}</td>
                  </tr>
                )}
                {Object.entries(row.byKind).map(([kind, n]) => (
                  <tr key={kind}>
                    <td>
                      <span className={styles.sub}>
                        of which {KIND_LABEL[kind] ?? kind}
                      </span>
                    </td>
                    <td data-num="">
                      <span className={styles.sub}>{count(n)}</span>
                    </td>
                    <td />
                  </tr>
                ))}
              </tbody>
            </Table>
            <Table label={`${row.environment} open holds by day`}>
              <thead>
                <tr>
                  <th scope="col">Made on</th>
                  <th scope="col" data-num="">
                    Open
                  </th>
                  <th scope="col" data-num="">
                    Canary
                  </th>
                  <th scope="col" data-num="">
                    Held
                  </th>
                </tr>
              </thead>
              <tbody>
                {row.recent.length ? (
                  row.recent.map((day) => (
                    <tr key={day.day}>
                      <th scope="row">{dayLabel(day.day)}</th>
                      <td data-num="">{count(day.n)}</td>
                      <td data-num="">{count(day.canary)}</td>
                      <td data-num="">{inr(day.heldRupees)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <th scope="row">Last two weeks</th>
                    <td data-num="">0</td>
                    <td data-num="">0</td>
                    <td data-num="">{inr(0)}</td>
                  </tr>
                )}
              </tbody>
            </Table>
          </div>
        </Panel>
      ))}
    </>
  );
}
