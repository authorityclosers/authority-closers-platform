/**
 * Usage & cost views (owner order, 19 Oct 2026): one Admin shows what Sales
 * X-Ray costs and earns in production, staging and dev. Server-rendered from
 * one read; every rupee is a list-price estimate from the price sheet.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { Coins, Gauge, GitCompare, Landmark, Receipt } from "lucide-react";

import {
  ENVIRONMENTS,
  ENVIRONMENT_LABEL,
  KIND_LABEL,
  STAGE_LABEL,
  comparePair,
  costQuery,
  count,
  dayLabel,
  inr,
  minutes,
  pct,
  perMin,
  seconds,
  stamp,
  tokens,
  type Metrics,
  type Pipeline,
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
};

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
      <div className={styles.columns}>
        <Panel
          title="Spend per day"
          sub={windowLabel}
          tools={
            <span className={styles.legend}>
              {ENVIRONMENTS.map((name) => (
                <Env key={name} name={name} />
              ))}
            </span>
          }
        >
          {o.spendWindow > 0 ? (
            <DailyBars metrics={metrics} />
          ) : (
            <Empty icon={Coins} title="No spend in this window" />
          )}
        </Panel>
        <Panel
          title="Cost per audio minute"
          sub="per day"
          tools={
            <Why detail="Each call's whole cost (transcription, facts, report, pointer review, repeats) on the day it was first transcribed, divided by its minutes of audio. A later backfill counts on the call's own day." />
          }
        >
          {o.audioMinutes > 0 ? (
            <PerMinuteBars metrics={metrics} />
          ) : (
            <Empty icon={Gauge} title="No audio transcribed in this window" />
          )}
        </Panel>
      </div>
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

/* ---------- Per call ---------- */

const STAGE_ORDER = ["C2", "C4", "C5", "PR"];

export function CallsView({ metrics }: { metrics: Metrics }) {
  const rows = metrics.calls.rows;
  if (!rows.length)
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
    <Panel
      title="Cost per call"
      sub={
        metrics.calls.total > rows.length
          ? `newest ${count(rows.length)} of ${count(metrics.calls.total)}`
          : `${count(rows.length)} calls`
      }
      tools={
        <Why detail="Each call's provider steps priced from the price sheet: transcription by audio length, facts, report and pointer review by tokens in and out. Margin needs a paid plan: plan price per included minute times the minutes billed, minus cost." />
      }
    >
      <Table
        label="Cost per call"
        cards={rows.map((row) => (
          <div key={`${row.environment}-${row.id}`} role="listitem">
            <Env name={row.environment} /> · {row.company} ·{" "}
            {minutes(row.audioMinutes)} · {inr(row.rupees)} (
            {perMin(row.perMinute)})
          </div>
        ))}
      >
        <thead>
          <tr>
            <th scope="col">Call</th>
            {STAGE_ORDER.map((stage) => (
              <th key={stage} scope="col" data-num="">
                {STAGE_LABEL[stage]}
              </th>
            ))}
            <th scope="col" data-num="">
              Total
            </th>
            <th scope="col" data-num="">
              Billed
            </th>
            <th scope="col" data-num="">
              Margin
            </th>
            <th scope="col" data-num="">
              Report in
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.environment}-${row.id}`}>
              <th scope="row">
                {metrics.here === row.environment ? (
                  <Link href={`/calls/${row.id}`}>{row.company}</Link>
                ) : (
                  row.company
                )}
                <span className={styles.sub}>
                  <Env name={row.environment} /> · {stamp(row.at)} ·{" "}
                  {minutes(row.audioMinutes)}
                  {row.kind !== "real"
                    ? ` · ${KIND_LABEL[row.kind] ?? row.kind}`
                    : ""}
                </span>
              </th>
              {STAGE_ORDER.map((stage) => {
                const cost = row.stages[stage];
                return (
                  <td key={stage} data-num="">
                    {cost ? inr(cost.rupees) : "–"}
                    {cost && (cost.inputTokens || cost.outputTokens) ? (
                      <span className={styles.sub}>
                        {tokens(cost.inputTokens)} in ·{" "}
                        {tokens(cost.outputTokens)} out
                      </span>
                    ) : null}
                    {cost && cost.runs > 1 ? (
                      <span className={styles.sub}>{cost.runs} runs</span>
                    ) : null}
                  </td>
                );
              })}
              <td data-num="">
                <strong>{inr(row.rupees)}</strong>
                <span className={styles.sub}>{perMin(row.perMinute)}</span>
              </td>
              <td data-num="">{minutes(row.billedMinutes)}</td>
              <td data-num="">
                {row.margin === null ? (
                  <span className={styles.sub}>no paid plan</span>
                ) : (
                  <span
                    className={row.margin >= 0 ? styles.better : styles.worse}
                  >
                    {inr(row.margin)}
                  </span>
                )}
              </td>
              <td data-num="">
                {row.report ? seconds(row.reportMs) : "no report"}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
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
      <Tiles label="Open budget holds">
        {money.environments.map((row) => (
          <Kpi
            key={row.environment}
            label={`${ENVIRONMENT_LABEL[row.environment] ?? row.environment} open holds`}
            value={count(row.open)}
            note={`${inr(row.openRupees)} held${
              row.capShare !== null
                ? ` · ${pct(row.capShare)} of the ${inr(row.cap)} cap`
                : ""
            }`}
          />
        ))}
      </Tiles>
      <Panel
        title="Why holds stay open"
        tools={<Badge tone="warn">needs the owner</Badge>}
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
