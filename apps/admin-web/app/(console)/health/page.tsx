import Link from "next/link";
import { CheckCircle2 } from "lucide-react";

import { when } from "@/app/calls/call-data";
import {
  JOB_STATUSES,
  JOB_STATUS_LABEL,
  STAGE_LABEL,
  normalizeHealth,
  rupees,
  span,
} from "@/app/health/health-data";
import styles from "@/app/health/health.module.css";
import { RetryJob } from "@/app/health/retry-job";
import { adminRead } from "@/app/lib/server-api";
import {
  Empty,
  Kpi,
  List,
  Page,
  PageHeader,
  Panel,
  QueryTabs,
  Row,
  Table,
  Tiles,
  Unavailable,
  Why,
} from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const WINDOWS = [
  { key: "7", label: "7 days" },
  { key: "1", label: "Today" },
  { key: "30", label: "30 days" },
];

export default async function HealthPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const { days } = await searchParams;
  const window = WINDOWS.find((item) => item.key === days)?.key ?? "7";
  const result = await adminRead(
    `/v1/admin/conversation/health?days=${window}`,
    normalizeHealth,
  );
  const health = result.ok ? result.data : null;
  const peak = Math.max(
    1,
    ...(health?.daily.map((day) => day.analysed + day.failed) ?? [1]),
  );
  return (
    <Page>
      <PageHeader
        title="Analysis health"
        context={[
          "Sales Xray analyses: what finished, failed, stalled, how long it took and what it cost",
        ]}
      />
      <QueryTabs base="/health" param="days" items={WINDOWS} current={window} />
      {!result.ok ? (
        <Unavailable title="Analysis health" reason={result.error} />
      ) : null}
      {health ? (
        <>
          <Tiles label="Health">
            <Kpi
              label="Reports made"
              value={
                health.byStage.find((row) => row.stage === "C5")?.counts
                  .succeeded ?? 0
              }
            />
            <Kpi
              label="Failed jobs"
              value={health.byStatus.dead_letter}
              tone={health.byStatus.dead_letter ? "bad" : "good"}
            />
            <Kpi
              label="Stuck now"
              value={health.stuck.length}
              tone={health.stuck.length ? "warn" : "good"}
            />
            <Kpi
              label="Retried"
              value={health.retried}
              note="Jobs that needed more than one attempt"
            />
            <Kpi
              label="Typical analysis"
              value={span(health.runs.p50)}
              note={`Slowest 10%: ${span(health.runs.p90)}`}
            />
            <Kpi
              label="Cost per minute"
              value={rupees(health.cost.paisePerMinute)}
              note={`Estimate over ${health.cost.minutes} min · not a bill`}
            />
          </Tiles>

          <div className={styles.columns}>
            <Panel
              title="Per day"
              tools={
                <span className={styles.legend}>
                  <span>Reports</span>
                  <span data-failed="">Failed</span>
                </span>
              }
            >
              <div
                className={styles.bars}
                role="img"
                aria-label="Reports and failures per day"
              >
                {health.daily.map((day) => (
                  <span
                    key={day.day}
                    className={styles.day}
                    title={`${day.day}: ${day.analysed} reports, ${day.failed} failed`}
                  >
                    <i
                      data-failed=""
                      style={{ height: `${(day.failed / peak) * 100}%` }}
                    />
                    <i style={{ height: `${(day.analysed / peak) * 100}%` }} />
                  </span>
                ))}
              </div>
              <div className={styles.axis} aria-hidden="true">
                <span>{health.daily[0]?.day}</span>
                <span>{health.daily.at(-1)?.day}</span>
              </div>
            </Panel>

            <Panel
              title="Stuck now"
              sub={health.stuckTruncated ? "first 50" : undefined}
              tools={
                <Why detail="Plans past their budget window and released runs that never finished, from the watchdog's overdue alarm." />
              }
            >
              {health.stuck.length ? (
                <List label="Stuck work">
                  {health.stuck.map((item) => (
                    <Row
                      key={`${item.kind}-${item.id}`}
                      title={
                        item.kind === "plan"
                          ? "Processing plan past its window"
                          : "Run released but unfinished"
                      }
                      href={
                        item.recordingId
                          ? `/calls/${item.recordingId}`
                          : undefined
                      }
                      meta={[
                        item.state,
                        item.since ? `since ${when(item.since)}` : null,
                        item.id.slice(0, 8),
                      ]}
                    />
                  ))}
                </List>
              ) : (
                <Empty icon={CheckCircle2} title="Nothing is stuck" />
              )}
            </Panel>
          </div>

          <Panel
            title="Failed jobs"
            sub={
              health.failed.length ? `${health.failed.length} shown` : undefined
            }
          >
            {health.failed.length ? (
              <Table label="Failed jobs">
                <thead>
                  <tr>
                    <th scope="col">Step</th>
                    <th scope="col">Failure</th>
                    <th scope="col" data-num="">
                      Attempts
                    </th>
                    <th scope="col">Failed</th>
                    <th scope="col">Call</th>
                    <th scope="col">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {health.failed.map((job) => (
                    <tr key={job.jobId}>
                      <th scope="row">{STAGE_LABEL[job.stage] ?? job.stage}</th>
                      <td className={styles.code}>{job.code}</td>
                      <td data-num="">{job.attempts}</td>
                      <td>{when(job.failedAt)}</td>
                      <td>
                        {job.recordingId ? (
                          <Link href={`/calls/${job.recordingId}`}>
                            Open call
                          </Link>
                        ) : (
                          "–"
                        )}
                      </td>
                      <td>
                        <RetryJob jobId={job.jobId} retryable={job.retryable} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <Empty
                icon={CheckCircle2}
                title="No failed jobs in this window"
              />
            )}
          </Panel>

          <div className={styles.columns}>
            <Panel
              title="Jobs by step"
              sub={
                health.truncated ? "newest 5,000 jobs" : `${health.total} jobs`
              }
            >
              <Table label="Jobs by step">
                <thead>
                  <tr>
                    <th scope="col">Step</th>
                    {JOB_STATUSES.map((status) => (
                      <th key={status} scope="col" data-num="">
                        {JOB_STATUS_LABEL[status]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {health.byStage.map((row) => (
                    <tr key={row.stage}>
                      <th scope="row">{STAGE_LABEL[row.stage] ?? row.stage}</th>
                      {JOB_STATUSES.map((status) => (
                        <td key={status} data-num="">
                          {row.counts[status]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Panel>
            <Panel
              title="Time per step"
              tools={
                <Why detail="Provider time is from dispatch to receipt for each provider job; a whole analysis is from run start to finish." />
              }
            >
              <Table label="Time per step">
                <thead>
                  <tr>
                    <th scope="col">Step</th>
                    <th scope="col" data-num="">
                      Jobs
                    </th>
                    <th scope="col" data-num="">
                      Typical
                    </th>
                    <th scope="col" data-num="">
                      Slowest 10%
                    </th>
                    <th scope="col" data-num="">
                      Slowest
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { stage: "Whole analysis", duration: health.runs },
                    ...health.providerByStage,
                  ].map((row) => (
                    <tr key={row.stage}>
                      <th scope="row">{STAGE_LABEL[row.stage] ?? row.stage}</th>
                      <td data-num="">{row.duration.count}</td>
                      <td data-num="">{span(row.duration.p50)}</td>
                      <td data-num="">{span(row.duration.p90)}</td>
                      <td data-num="">{span(row.duration.max)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Panel>
          </div>
        </>
      ) : null}
    </Page>
  );
}
