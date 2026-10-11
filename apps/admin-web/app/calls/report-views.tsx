"use client";

/**
 * What the reviewer reads beside the call: the report as it stands today, the
 * same report in the six pillars, the per-call Coaching, call metrics and the
 * analysis runs. Every quote is a button that plays the call from that moment.
 */
import Link from "next/link";
import { Play } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "../ui/kit";
import { DEVANAGARI } from "./transcript-pane";
import {
  clock,
  languageLabel,
  when,
  type Bundle,
  type Call,
  type Evidence,
  type Finding,
  type Report,
} from "./call-data";
import {
  reportPillars,
  REPORT_SKILLS,
  skillState,
  type ReportPillar,
} from "./report-pillars";
import { compareReports } from "./review-logic";
import styles from "./review.module.css";

type OnEvidence = (evidence: Evidence) => void;

export function Quote({
  evidence,
  onEvidence,
}: {
  evidence: Evidence;
  onEvidence: OnEvidence;
}) {
  return (
    <button
      type="button"
      className={styles.quote}
      onClick={() => onEvidence(evidence)}
      title={`Play from ${clock(evidence.startMs)}`}
    >
      <Play size={11} aria-hidden="true" />
      <time>{clock(evidence.startMs)}</time>
      <q data-script={DEVANAGARI.test(evidence.quote) ? "deva" : undefined}>
        {evidence.quote}
      </q>
    </button>
  );
}

function Quotes({
  items,
  onEvidence,
}: {
  items: Evidence[];
  onEvidence: OnEvidence;
}) {
  return items.length ? (
    <div className={styles.quotes}>
      {items.map((item, index) => (
        <Quote
          key={`${item.segmentId}-${index}`}
          evidence={item}
          onEvidence={onEvidence}
        />
      ))}
    </div>
  ) : null;
}

function Block({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.block} aria-label={title}>
      <h3 className={styles.blockTitle}>
        {title}
        {sub ? <small>{sub}</small> : null}
      </h3>
      {children}
    </section>
  );
}

function Findings({
  items,
  empty,
  onEvidence,
}: {
  items: Finding[];
  empty: string;
  onEvidence: OnEvidence;
}) {
  if (!items.length) return <p className={styles.gap}>{empty}</p>;
  return (
    <ol className={styles.findings}>
      {items.map((item, index) => (
        <li key={`${item.title}-${index}`}>
          <strong>{item.title}</strong>
          <p>{item.explanation}</p>
          <Quotes items={item.evidence} onEvidence={onEvidence} />
        </li>
      ))}
    </ol>
  );
}

/** The report exactly as stored: the order and fields of the report contract. */
export function CurrentReport({
  report,
  onEvidence,
}: {
  report: Report;
  onEvidence: OnEvidence;
}) {
  return (
    <div className={styles.reading}>
      <Block title="Summary">
        <p>{report.summary || "No summary."}</p>
        <Quotes items={report.summaryEvidence} onEvidence={onEvidence} />
      </Block>
      <Block title="Verdict">
        <p>{report.verdict || "No verdict."}</p>
        <Quotes items={report.verdictEvidence} onEvidence={onEvidence} />
      </Block>
      <Block title="Strengths" sub={report.strengths.length}>
        <Findings
          items={report.strengths}
          empty="No strengths were supplied."
          onEvidence={onEvidence}
        />
      </Block>
      <Block title="What to improve" sub={report.improvements.length}>
        <Findings
          items={report.improvements}
          empty="No improvements were supplied."
          onEvidence={onEvidence}
        />
      </Block>
      <Block
        title="Missed opportunities"
        sub={report.missedOpportunities.length}
      >
        <Findings
          items={report.missedOpportunities}
          empty="No missed opportunities were supplied."
          onEvidence={onEvidence}
        />
      </Block>
      <Block title="Objections" sub={report.objectionAnalysis.length}>
        <Findings
          items={report.objectionAnalysis}
          empty="No objections were analysed."
          onEvidence={onEvidence}
        />
      </Block>
      <Block title="Closing" sub={report.closingAnalysis.length}>
        <Findings
          items={report.closingAnalysis}
          empty="No closing analysis was supplied."
          onEvidence={onEvidence}
        />
      </Block>
      <Block title="Skills on this call">
        <ul className={styles.skills}>
          {REPORT_SKILLS.map(([id, label]) => {
            const dimension = report.dimensions.find((item) => item.id === id);
            const state = dimension ? skillState(dimension) : null;
            return (
              <li key={id}>
                <span className={styles.skillHead}>
                  <strong>{label}</strong>
                  <Badge tone={state ? "accent" : "neutral"}>
                    {state ?? "Not established"}
                  </Badge>
                </span>
                {dimension ? (
                  <p>{dimension.observation}</p>
                ) : (
                  <p className={styles.gap}>Not assessed.</p>
                )}
                {dimension ? (
                  <Quotes items={dimension.evidence} onEvidence={onEvidence} />
                ) : null}
              </li>
            );
          })}
        </ul>
      </Block>
    </div>
  );
}

function PillarView({
  pillar,
  index,
  durationMs,
  onEvidence,
}: {
  pillar: ReportPillar;
  index: number;
  durationMs: number | null;
  onEvidence: OnEvidence;
}) {
  return (
    <section
      className={styles.pillar}
      id={`pillar-${pillar.id}`}
      aria-label={pillar.label}
    >
      <h3 className={styles.pillarTitle}>
        <span>{index + 1}</span>
        {pillar.label}
      </h3>
      {pillar.timeline?.length && durationMs ? (
        <div
          className={styles.timeline}
          role="img"
          aria-label="Conversation phases"
        >
          {pillar.timeline.map((phase) => (
            <span
              key={`${phase.label}-${phase.startMs}`}
              style={{ flexGrow: Math.max(1, phase.endMs - phase.startMs) }}
              title={`${phase.label} · ${clock(phase.startMs)}–${clock(phase.endMs)}`}
            >
              {phase.label}
            </span>
          ))}
        </div>
      ) : null}
      <ul className={styles.entries}>
        {pillar.entries.map((entry, entryIndex) => (
          <li
            key={`${entry.label}-${entryIndex}`}
            data-gap={entry.gap ? "" : undefined}
          >
            <span className={styles.entryLabel}>
              {entry.label}
              {entry.hypothesis ? (
                <Badge tone="warn">Working hypothesis</Badge>
              ) : null}
            </span>
            <p>{entry.text}</p>
            <Quotes items={entry.evidence} onEvidence={onEvidence} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The same report in the spec's six pillars, as the rep's Story view shows it. */
export function Pillars({
  report,
  durationMs,
  onEvidence,
}: {
  report: Report;
  durationMs: number | null;
  onEvidence: OnEvidence;
}) {
  const pillars = reportPillars(report, durationMs);
  return (
    <div className={styles.reading}>
      <nav className={styles.pillarNav} aria-label="Pillars">
        {pillars.map((pillar, index) => (
          <a key={pillar.id} href={`#pillar-${pillar.id}`}>
            {index + 1}. {pillar.label}
          </a>
        ))}
      </nav>
      {pillars.map((pillar, index) => (
        <PillarView
          key={pillar.id}
          pillar={pillar}
          index={index}
          durationMs={durationMs}
          onEvidence={onEvidence}
        />
      ))}
    </div>
  );
}

/**
 * Per-call Coaching in the spec's six coaching pillars, from this call's
 * report only. Pattern and progress need several calls, so they stay gaps.
 */
export function Coaching({
  report,
  onEvidence,
}: {
  report: Report;
  onEvidence: OnEvidence;
}) {
  const overview = report.overview;
  if (!overview)
    return (
      <p className={styles.gap}>
        This report has no coaching section (an older report format). Re-running
        the call with a current prompt adds one.
      </p>
    );
  const better = overview.improvementDetails.filter(
    (item) => item.replacementBehavior,
  );
  return (
    <div className={styles.reading}>
      <Block title="1. What to work on now">
        {overview.nextCallFocus ? (
          <>
            <p>
              <strong>{overview.nextCallFocus.behavior}</strong>
            </p>
            <p>Target: {overview.nextCallFocus.target}</p>
          </>
        ) : overview.finalAssessment?.fixFirst ? (
          <p>
            <strong>{overview.finalAssessment.fixFirst}</strong>
          </p>
        ) : (
          <p className={styles.gap}>No focus was supplied.</p>
        )}
      </Block>
      <Block title="2. Why this keeps happening" sub="working hypothesis">
        {overview.diagnosis ? (
          <>
            <p>{overview.diagnosis.text}</p>
            <Quotes
              items={overview.diagnosis.evidence}
              onEvidence={onEvidence}
            />
          </>
        ) : null}
        <p className={styles.gap}>
          A pattern needs several calls; one call&rsquo;s report can&rsquo;t
          establish a root cause.
        </p>
      </Block>
      <Block title="3. What better looks like">
        {better.length ? (
          <ol className={styles.findings}>
            {better.map((item, index) => (
              <li key={index}>
                <strong>
                  {report.improvements[item.findingIndex]?.title ??
                    "Improvement"}
                </strong>
                <p>{item.replacementBehavior}</p>
                {item.whatHappened.text ? (
                  <p className={styles.muted}>
                    What happened: {item.whatHappened.text}
                  </p>
                ) : null}
                <Quotes
                  items={item.whatHappened.evidence}
                  onEvidence={onEvidence}
                />
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.gap}>No better behaviour was supplied.</p>
        )}
      </Block>
      <Block title="4. Try this on your next call">
        {overview.practiceDrill ? (
          <>
            <p>{overview.practiceDrill.instructions}</p>
            <p>Done when: {overview.practiceDrill.successCondition}</p>
          </>
        ) : (
          <p className={styles.gap}>No practice was supplied.</p>
        )}
      </Block>
      <Block title="5. See how you're improving">
        <p className={styles.gap}>
          Progress needs earlier calls; a single call&rsquo;s report never
          infers it.
        </p>
      </Block>
      <Block title="6. Where we go from here">
        {overview.finalAssessment ? (
          <dl className={styles.facts}>
            <dt>Repeat</dt>
            <dd>{overview.finalAssessment.repeat}</dd>
            <dt>Fix first</dt>
            <dd>{overview.finalAssessment.fixFirst}</dd>
            <dt>Next focus</dt>
            <dd>{overview.finalAssessment.nextFocus}</dd>
            <dt>Assessment</dt>
            <dd>{overview.finalAssessment.assessment}</dd>
          </dl>
        ) : (
          <p className={styles.gap}>No direction was supplied.</p>
        )}
      </Block>
    </div>
  );
}

/** call-metrics/2 per speaker: evidence about the conversation, not a judgement. */
export function Metrics({
  bundle,
  names,
}: {
  bundle: Bundle;
  names: Record<string, string>;
}) {
  const metrics = bundle.metrics;
  if (!metrics || !Object.keys(metrics.speakers).length)
    return (
      <p className={styles.gap}>
        Call metrics aren&rsquo;t available for this run.
      </p>
    );
  const percent = (value: number | null) =>
    value === null ? "–" : `${Math.round(value * 100)}%`;
  return (
    <div className={styles.reading}>
      <p className={styles.muted}>
        Measured from the transcript (call-metrics/2). Metrics are evidence, not
        judgement.
      </p>
      <table className={styles.metrics}>
        <thead>
          <tr>
            <th scope="col">Speaker</th>
            <th scope="col">Talk share</th>
            <th scope="col">Talk time</th>
            <th scope="col">Questions</th>
            <th scope="col">Per minute</th>
            <th scope="col">Talk-overs</th>
            <th scope="col">Longest turn</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(metrics.speakers).map(([id, row]) => (
            <tr key={id}>
              <th scope="row">{names[id] ?? id}</th>
              <td>{percent(row.talkShare)}</td>
              <td>{clock(row.talkMs)}</td>
              <td>{row.questions}</td>
              <td>
                {row.questionsPerMinute === null
                  ? "–"
                  : row.questionsPerMinute.toFixed(1)}
              </td>
              <td>{row.cutIns}</td>
              <td>{clock(row.longestMonologueMs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Every analysis of this call; open one, or compare two side by side. */
export function Runs({
  call,
  current,
  compare,
  compareBundle,
  baseHref,
}: {
  call: Call;
  current: Bundle;
  compare: string | null;
  compareBundle: Bundle | null;
  baseHref: (query: Record<string, string | null>) => string;
}) {
  const rows = compareBundle
    ? compareReports(current.report, compareBundle.report)
    : [];
  return (
    <div className={styles.reading}>
      <ul className={styles.runs}>
        {call.runs.map((run) => {
          const isCurrent = run.id === current.runId;
          return (
            <li key={run.id} data-current={isCurrent ? "" : undefined}>
              <span className={styles.runHead}>
                <strong>{when(run.createdAt)}</strong>
                <Badge
                  tone={
                    run.reportId
                      ? "good"
                      : run.state === "failed"
                        ? "bad"
                        : "neutral"
                  }
                >
                  {run.reportId ? "Report" : run.state}
                </Badge>
                {isCurrent ? <Badge tone="accent">Open</Badge> : null}
                {run.id === compare ? (
                  <Badge tone="warn">Comparing</Badge>
                ) : null}
              </span>
              <span className={styles.runMeta}>
                {[
                  run.model ?? run.provider,
                  run.promptRevision,
                  run.factPromptRevision,
                  run.settingsRevision
                    ? `settings #${run.settingsRevision}`
                    : null,
                  languageLabel(run.language),
                  run.outputProfile,
                  run.retryOf ? "retry" : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {run.reportId && !isCurrent ? (
                <span className={styles.runActions}>
                  <Link href={baseHref({ run: run.id, compare: null })}>
                    Open
                  </Link>
                  <Link
                    href={baseHref({
                      compare: run.id === compare ? null : run.id,
                    })}
                  >
                    {run.id === compare
                      ? "Stop comparing"
                      : "Compare with open run"}
                  </Link>
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
      {compareBundle ? (
        <table className={styles.compare} aria-label="Run comparison">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Open run</th>
              <th scope="col">Compared run</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} data-changed={row.same ? undefined : ""}>
                <th scope="row">
                  {row.label}
                  {row.same ? null : <Badge tone="warn">Changed</Badge>}
                </th>
                <td>{row.left}</td>
                <td>{row.right}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : compare ? (
        <p className={styles.gap}>
          The compared run&rsquo;s report couldn&rsquo;t be loaded.
        </p>
      ) : call.runs.filter((run) => run.reportId).length > 1 ? (
        <p className={styles.muted}>
          Choose “Compare with open run” to see what changed between prompts or
          providers.
        </p>
      ) : (
        <p className={styles.muted}>Only one run of this call has a report.</p>
      )}
    </div>
  );
}
