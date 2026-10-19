/**
 * Analysis health, Phase 4 (owner 19 Oct: real analysis health): the call data
 * engine's runs per pipeline and version, and Review 2.0's measures of how
 * often reviewers judged the analysis right and agreed with each other.
 */
import { ClipboardCheck, Cpu } from "lucide-react";

import { when } from "../calls/call-data";
import {
  Badge,
  Card,
  Empty,
  List,
  Meter,
  Panel,
  Row,
  Table,
  Why,
} from "../ui/kit";
import type { EngineHealth, ReviewHealth, ReviewQuestion } from "./engine-data";
import { PIPELINE_LABEL, inr, percent, typeLabel } from "./engine-data";
import { span } from "./health-data";
import styles from "./engine-panels.module.css";

const tone = (value: number | null) =>
  value === null
    ? "neutral"
    : value >= 0.9
      ? "good"
      : value >= 0.7
        ? "warn"
        : "bad";

function ShareMeter({ value, label }: { value: number | null; label: string }) {
  return (
    <span className={styles.share}>
      {value === null ? null : <Meter value={value} max={1} label={label} />}
      <span>{percent(value)}</span>
    </span>
  );
}

export function EngineHealthPanels({ data }: { data: EngineHealth }) {
  const pipelines = data.pipelines;
  const peak = Math.max(
    1,
    ...data.daily.map((day) =>
      Object.values(day.counts).reduce(
        (sum, counts) => sum + counts.succeeded + counts.failed,
        0,
      ),
    ),
  );
  const reasons = pipelines.flatMap((row) =>
    row.reasons.map((reason) => ({ ...reason, pipeline: row.pipeline })),
  );
  if (!pipelines.length) {
    return (
      <Panel title="Call data engine">
        <Empty
          icon={Cpu}
          title="No engine runs in this read"
          text="The API did not return the call data engine's runs for this window."
        />
      </Panel>
    );
  }
  return (
    <>
      <Panel
        title="Call data engine"
        sub={
          data.truncated
            ? "newest 20,000 runs"
            : "Runs that ended in this window"
        }
        tools={
          <Why detail="Each call goes through the fast pipeline (facts and objects in seconds) and, when switched on, the deep one. Success leaves out skips (calls too long or silent), which never reach the model. Cost is what each run recorded; time is the run's own clock." />
        }
      >
        <Table
          label="Engine pipelines"
          cards={pipelines.map((row) => (
            <Card key={row.pipeline}>
              <strong>
                {PIPELINE_LABEL[row.pipeline] ?? row.pipeline}
                {row.version ? (
                  <span className={styles.code}> {row.version}</span>
                ) : null}
              </strong>
              <span>
                {row.succeeded} done · {row.failed} failed · {row.skipped}{" "}
                skipped · success {percent(row.successShare)}
              </span>
              <span>
                Typical {span(row.time.p50)} · slowest 10% {span(row.time.p90)}{" "}
                · {inr(row.costInr)} ({inr(row.costPerRunInr)} a run)
              </span>
              {row.running || row.quiet ? (
                <span>
                  {row.running} running · {row.quiet} gone quiet
                </span>
              ) : null}
            </Card>
          ))}
        >
          <thead>
            <tr>
              <th scope="col">Pipeline</th>
              <th scope="col" data-num="">
                Runs
              </th>
              <th scope="col" data-num="">
                Done
              </th>
              <th scope="col" data-num="">
                Failed
              </th>
              <th scope="col" data-num="">
                Skipped
              </th>
              <th scope="col">Success</th>
              <th scope="col" data-num="">
                Typical
              </th>
              <th scope="col" data-num="">
                Slowest 10%
              </th>
              <th scope="col" data-num="">
                Cost
              </th>
              <th scope="col" data-num="">
                A run
              </th>
              <th scope="col" data-num="">
                Now
              </th>
            </tr>
          </thead>
          <tbody>
            {pipelines.map((row) => (
              <tr key={row.pipeline}>
                <th scope="row">
                  {PIPELINE_LABEL[row.pipeline] ?? row.pipeline}
                  {row.version ? (
                    <small className={styles.code}> {row.version}</small>
                  ) : null}
                </th>
                <td data-num="">{row.runs}</td>
                <td data-num="">{row.succeeded}</td>
                <td data-num="">{row.failed}</td>
                <td data-num="">{row.skipped}</td>
                <td>
                  <ShareMeter
                    value={row.successShare}
                    label={`${PIPELINE_LABEL[row.pipeline] ?? row.pipeline} success`}
                  />
                </td>
                <td data-num="">{span(row.time.p50)}</td>
                <td data-num="">{span(row.time.p90)}</td>
                <td data-num="">{inr(row.costInr)}</td>
                <td data-num="">{inr(row.costPerRunInr)}</td>
                <td data-num="">
                  {row.running || row.quiet ? (
                    <>
                      {row.running} running
                      {row.quiet ? (
                        <Badge tone="warn">{row.quiet} quiet</Badge>
                      ) : null}
                    </>
                  ) : (
                    "–"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>

      <div className={styles.columns}>
        <Panel
          title="Engine runs per day"
          tools={
            <span className={styles.legend}>
              {pipelines.map((row) => (
                <span key={row.pipeline} data-pipeline={row.pipeline}>
                  {PIPELINE_LABEL[row.pipeline] ?? row.pipeline}
                </span>
              ))}
              <span data-failed="">Failed</span>
            </span>
          }
        >
          <div
            className={styles.bars}
            role="img"
            aria-label="Engine runs per day"
          >
            {data.daily.map((day) => {
              const failed = Object.values(day.counts).reduce(
                (sum, counts) => sum + counts.failed,
                0,
              );
              return (
                <span
                  key={day.day}
                  className={styles.day}
                  title={`${day.day}: ${pipelines
                    .map(
                      (row) =>
                        `${PIPELINE_LABEL[row.pipeline] ?? row.pipeline} ${day.counts[row.pipeline]?.succeeded ?? 0} done`,
                    )
                    .join(", ")}, ${failed} failed`}
                >
                  <i
                    data-failed=""
                    style={{ height: `${(failed / peak) * 100}%` }}
                  />
                  {pipelines.map((row) => (
                    <i
                      key={row.pipeline}
                      data-pipeline={row.pipeline}
                      style={{
                        height: `${((day.counts[row.pipeline]?.succeeded ?? 0) / peak) * 100}%`,
                      }}
                    />
                  ))}
                </span>
              );
            })}
          </div>
          <div className={styles.axis} aria-hidden="true">
            <span>{data.daily[0]?.day}</span>
            <span>{data.daily.at(-1)?.day}</span>
          </div>
        </Panel>

        <Panel
          title="Why runs failed or were skipped"
          tools={
            <Why detail="Stored reason codes only. A reason that is not a code reads 'withheld': provider and call text never reach this view." />
          }
        >
          {reasons.length ? (
            <ol className={styles.reasons}>
              {reasons.map((reason) => (
                <li key={`${reason.pipeline}-${reason.state}-${reason.code}`}>
                  <span>
                    <Badge tone={reason.state === "failed" ? "bad" : "neutral"}>
                      {reason.state === "failed" ? "Failed" : "Skipped"}
                    </Badge>{" "}
                    <span className={styles.code}>{reason.code}</span>
                  </span>
                  <small>
                    {PIPELINE_LABEL[reason.pipeline] ?? reason.pipeline} ·{" "}
                    {reason.runs}
                  </small>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.none}>
              No failed or skipped runs in this window.
            </p>
          )}
          {data.quiet.length ? (
            <>
              <h3 className={styles.subhead}>Gone quiet</h3>
              <List label="Runs gone quiet">
                {data.quiet.map((item) => (
                  <Row
                    key={item.runId}
                    title={`${PIPELINE_LABEL[item.pipeline] ?? item.pipeline} run with no outcome`}
                    href={`/calls/${item.recordingId}?tab=analysis`}
                    meta={[
                      item.startedAt ? `started ${when(item.startedAt)}` : null,
                      item.runId.slice(0, 8),
                    ]}
                  />
                ))}
              </List>
            </>
          ) : null}
        </Panel>
      </div>

      {data.versions.length ? (
        <Panel
          title="By engine version"
          tools={
            <Why detail="The same outcomes per pipeline version, newest first, to compare a new version with the one before it." />
          }
        >
          <Table label="By engine version">
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col" data-num="">
                  Runs
                </th>
                <th scope="col">Success</th>
                <th scope="col" data-num="">
                  Typical
                </th>
                <th scope="col" data-num="">
                  A run
                </th>
                <th scope="col">Last run</th>
              </tr>
            </thead>
            <tbody>
              {data.versions.map((row) => (
                <tr key={`${row.pipeline}-${row.version}`}>
                  <th scope="row">
                    {PIPELINE_LABEL[row.pipeline] ?? row.pipeline}{" "}
                    <span className={styles.code}>{row.version}</span>
                  </th>
                  <td data-num="">{row.runs}</td>
                  <td>
                    <ShareMeter
                      value={row.successShare}
                      label={`${row.version} success`}
                    />
                  </td>
                  <td data-num="">{span(row.time.p50)}</td>
                  <td data-num="">{inr(row.costPerRunInr)}</td>
                  <td>{row.lastAt ? when(row.lastAt) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
    </>
  );
}

function questionLine(question: ReviewQuestion): string {
  if (question.counts) {
    return (
      Object.entries(question.counts)
        .map(([option, count]) => `${count} ${option}`)
        .join(" · ") || "No answers"
    );
  }
  if (question.kind === "scale") {
    return question.average === null
      ? "No answers"
      : `${question.average.toFixed(1)} of 5 on average`;
  }
  return `${question.answers} ${question.answers === 1 ? "correction" : "corrections"}`;
}

export function ReviewHealthPanels({ data }: { data: ReviewHealth }) {
  if (!data.answers) {
    return (
      <Panel
        title="Review 2.0"
        sub="How often reviewers judged the analysis right"
      >
        <Empty
          icon={ClipboardCheck}
          title="No review answers in this window"
          text="Gold reviewers judge the analysis in Analysis review; their answers are measured here."
          action={{ href: "/analysis-review", label: "Open Analysis review" }}
        />
      </Panel>
    );
  }
  return (
    <>
      <div className={styles.columns}>
        {data.pipelines.map((pipeline) => (
          <Panel
            key={pipeline.key}
            title={pipeline.title}
            sub={`${pipeline.answers} answers · ${pipeline.items} items · ${pipeline.calls} calls · ${pipeline.reviewers} ${pipeline.reviewers === 1 ? "reviewer" : "reviewers"}`}
            tools={
              <Why detail="Each reviewer's current answer only (a changed answer replaces the old one). Right share counts the first option (correct, true) against the second (wrong, false); unsure is left out. Agreement: of the claims two or more reviewers judged, how many got the same answer from all of them." />
            }
          >
            <dl className={styles.facts}>
              <div>
                <dt>Judged right</dt>
                <dd>
                  <ShareMeter
                    value={pipeline.rightShare}
                    label={`${pipeline.title}: judged right`}
                  />
                  <small>
                    {pipeline.right} of {pipeline.right + pipeline.wrong}
                  </small>
                </dd>
              </div>
              <div>
                <dt>Reviewers agreed</dt>
                <dd>
                  {pipeline.agreement.compared ? (
                    <>
                      <Badge tone={tone(pipeline.agreement.share)}>
                        {percent(pipeline.agreement.share)}
                      </Badge>
                      <small>
                        {pipeline.agreement.agreed} of{" "}
                        {pipeline.agreement.compared} shared claims
                      </small>
                    </>
                  ) : (
                    <small>No claim has two reviewers yet</small>
                  )}
                </dd>
              </div>
              {pipeline.questions.map((question) => (
                <div key={question.key}>
                  <dt>{question.label}</dt>
                  <dd>
                    <small>{questionLine(question)}</small>
                  </dd>
                </div>
              ))}
            </dl>
            {pipeline.types.length ? (
              <Table label={`${pipeline.title} by type`}>
                <thead>
                  <tr>
                    <th scope="col">Type</th>
                    <th scope="col" data-num="">
                      Answers
                    </th>
                    <th scope="col">Judged right</th>
                  </tr>
                </thead>
                <tbody>
                  {pipeline.types.map((type) => (
                    <tr key={type.type}>
                      <th scope="row" title={type.type}>
                        {typeLabel(type.type)}
                      </th>
                      <td data-num="">{type.answers}</td>
                      <td>
                        <ShareMeter
                          value={type.rightShare}
                          label={`${typeLabel(type.type)}: judged right`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : null}
          </Panel>
        ))}
      </div>
      <div className={styles.columns}>
        <Panel
          title="Judged right by engine version"
          tools={
            <Why detail="Answers on call objects, grouped by the engine pipeline and version that made them, to see whether a new version is judged right more often." />
          }
        >
          {data.engineVersions.length ? (
            <Table label="Judged right by engine version">
              <thead>
                <tr>
                  <th scope="col">Version</th>
                  <th scope="col" data-num="">
                    Answers
                  </th>
                  <th scope="col">Judged right</th>
                </tr>
              </thead>
              <tbody>
                {data.engineVersions.map((row) => (
                  <tr key={`${row.pipeline}-${row.version}`}>
                    <th scope="row">
                      {PIPELINE_LABEL[row.pipeline] ?? row.pipeline}{" "}
                      <span className={styles.code}>{row.version}</span>
                    </th>
                    <td data-num="">{row.answers}</td>
                    <td>
                      <ShareMeter
                        value={row.rightShare}
                        label={`${row.version}: judged right`}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <Empty icon={Cpu} title="No answers on engine objects yet" />
          )}
        </Panel>
        <Panel
          title="Reviewers"
          sub={`${data.answers} answers on ${data.calls} calls`}
        >
          <List label="Reviewers">
            {data.reviewers.map((reviewer) => (
              <Row
                key={reviewer.name + reviewer.answers}
                title={reviewer.name}
                meta={[
                  `${reviewer.answers} ${reviewer.answers === 1 ? "answer" : "answers"}`,
                  `${reviewer.calls} ${reviewer.calls === 1 ? "call" : "calls"}`,
                ]}
              />
            ))}
          </List>
        </Panel>
      </div>
    </>
  );
}
