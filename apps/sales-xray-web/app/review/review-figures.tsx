"use client";

/**
 * The gold set in numbers (owner, 19 Oct): how big it is, where it is thin,
 * where the AI is wrong most, and where reviewers disagree with each other.
 * Counts only; no call content reaches this page.
 */

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import {
  REASON_WORDS,
  STATUS_WORDS,
  percent,
  readMetrics,
  type AiStatus,
  type Metrics,
  type PointerFigures,
} from "./review-client";
import { toneOf } from "./review-flow";
import styles from "./review.module.css";

function Stack({ figures }: { figures: PointerFigures }) {
  const total = figures.agree + figures.partly + figures.disagree;
  if (!total) return <span className={styles.stack} />;
  return (
    <span
      className={styles.stack}
      role="img"
      aria-label={`${figures.agree} agree, ${figures.partly} partly, ${figures.disagree} disagree`}
    >
      <span
        data-tone="good"
        style={{ width: `${(figures.agree / total) * 100}%` }}
      />
      <span
        data-tone="warn"
        style={{ width: `${(figures.partly / total) * 100}%` }}
      />
      <span
        data-tone="bad"
        style={{ width: `${(figures.disagree / total) * 100}%` }}
      />
    </span>
  );
}

function FiguresSkeleton() {
  return (
    <>
      <span className={styles.skeleton} style={{ width: 180, height: 26 }} />
      <div className={styles.tiles}>
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className={styles.skeleton} style={{ height: 64 }} />
        ))}
      </div>
      <div className={styles.twoCol}>
        <span className={styles.skeleton} style={{ height: 260 }} />
        <span className={styles.skeleton} style={{ height: 260 }} />
      </div>
      <span className={styles.skeleton} style={{ height: 420 }} />
    </>
  );
}

export function ReviewFiguresSkeleton() {
  return (
    <AcquisitionShell authenticated loading active="review">
      <div className={styles.root} aria-busy="true">
        <FiguresSkeleton />
      </div>
    </AcquisitionShell>
  );
}

export function ReviewFigures() {
  const [data, setData] = useState<Metrics | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    readMetrics(controller.signal)
      .then(setData)
      .catch((error: Error) => {
        if (error.name !== "AbortError") setProblem(error.message);
      });
    return () => controller.abort();
  }, []);

  const byTarget = new Map(data?.pointers.map((p) => [p.target, p]) ?? []);
  const wrong = (data?.wrong_most ?? [])
    .map((target) => byTarget.get(target))
    .filter((p): p is PointerFigures => Boolean(p));
  const team = data?.team;
  const thinnest = [...(data?.pointers ?? [])]
    .sort((a, b) => a.labels - b.labels)
    .slice(0, 5);
  const coverage = Object.entries(data?.ai_status_coverage ?? {}).sort(
    (a, b) => b[1] - a[1],
  );
  const daily = data?.me?.daily ?? [];
  const peak = Math.max(1, ...daily.map((day) => day.labels));

  return (
    <AcquisitionShell authenticated active="review" pageName="Gold set">
      <div className={styles.root}>
        {problem ? (
          <div className={styles.panel}>
            <h2>The figures didn&apos;t load</h2>
            <p className={styles.muted}>{problem}</p>
          </div>
        ) : !data || !team ? (
          <FiguresSkeleton />
        ) : (
          <>
            <div className={styles.head}>
              <div>
                <h1>Gold set</h1>
                <p>
                  Human labels on the AI&apos;s Report. The AI&apos;s scores
                  stay its draft; these answers are the reference.
                </p>
              </div>
              <Link className={styles.barChip} href="/review">
                <ArrowLeft size={14} aria-hidden="true" /> Review
              </Link>
            </div>
            <div className={styles.tiles}>
              <div className={styles.tile} data-tone="accent">
                <b>{team.labels}</b>
                <span>
                  labels · {team.calls_covered} calls · {team.reviewers}{" "}
                  reviewer
                  {team.reviewers === 1 ? "" : "s"}
                </span>
              </div>
              <div className={styles.tile}>
                <b>{team.today}</b>
                <span>labels today</span>
              </div>
              <div className={styles.tile}>
                <b>{percent(team.agreement)}</b>
                <span>agree with the AI</span>
              </div>
              <div className={styles.tile}>
                <b>
                  {team.median_seconds != null
                    ? `${Math.round(team.median_seconds)}s`
                    : "–"}
                </b>
                <span>per line</span>
              </div>
              <div className={styles.tile}>
                <b>{team.skipped}</b>
                <span>lines skipped</span>
              </div>
            </div>

            <div className={styles.twoCol}>
              <section className={styles.panel}>
                <h2>Where the AI is wrong most</h2>
                {wrong.length ? (
                  <ul className={styles.figures}>
                    {wrong.map((p) => (
                      <li key={p.target} className={styles.figure}>
                        <b>{p.label}</b>
                        <span className={styles.pill} data-tone="bad">
                          {percent(p.wrong_rate)} wrong
                        </span>
                        <Stack figures={p} />
                        <span
                          className={styles.muted}
                          style={{ gridColumn: "1 / -1" }}
                        >
                          {p.labels} labels
                          {p.mean_score_gap != null
                            ? ` · scores off by ${p.mean_score_gap}`
                            : ""}
                          {p.top_reasons.length
                            ? ` · ${p.top_reasons.map((r) => REASON_WORDS[r] ?? r).join(", ")}`
                            : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.muted}>No labels yet.</p>
                )}
              </section>
              <section className={styles.panel}>
                <h2>Reviewers on the same call</h2>
                {data.between_reviewers.lines ? (
                  <>
                    <p>
                      <b>{percent(data.between_reviewers.agreement)}</b> same
                      answer on {data.between_reviewers.lines} lines in{" "}
                      {data.between_reviewers.calls} calls
                    </p>
                    <ul className={styles.figures}>
                      {data.between_reviewers.by_line.map((line) => (
                        <li key={line.target} className={styles.figure}>
                          <span>{line.label}</span>
                          <span className={styles.pill} data-tone="warn">
                            {line.differ}/{line.lines} differ
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className={styles.muted}>
                    Shows once two reviewers label the same call.
                  </p>
                )}
                <h2>What the AI said, labelled</h2>
                <div className={styles.inline}>
                  {coverage.length ? (
                    coverage.map(([status, count]) => (
                      <span
                        key={status}
                        className={styles.pill}
                        data-tone={toneOf(status)}
                      >
                        {STATUS_WORDS[status as AiStatus] ?? status} · {count}
                      </span>
                    ))
                  ) : (
                    <span className={styles.muted}>No labels yet.</span>
                  )}
                </div>
                <h2>Thinnest lines</h2>
                <p className={styles.muted}>
                  {thinnest.map((p) => `${p.label} (${p.labels})`).join(" · ")}
                </p>
              </section>
            </div>

            {data.me ? (
              <section className={styles.panel}>
                <h2>Your last 14 days</h2>
                <div
                  className={styles.days}
                  role="img"
                  aria-label="Labels per day"
                >
                  {daily.map((day) => (
                    <span
                      key={day.date}
                      title={`${day.date}: ${day.labels}`}
                      data-zero={day.labels ? undefined : ""}
                      style={{
                        height: `${Math.max(4, (day.labels / peak) * 100)}%`,
                      }}
                    />
                  ))}
                </div>
                <p className={styles.muted}>
                  {data.me.labels} labels · {data.me.calls_done} calls finished
                  · {data.me.calls_left} waiting
                </p>
              </section>
            ) : null}

            <section className={styles.panel}>
              <h2>Every line</h2>
              <ul className={styles.figures}>
                {data.pointers.map((p) => (
                  <li key={p.target} className={styles.figure}>
                    <span>{p.label}</span>
                    <span className={styles.muted}>
                      {p.labels} · {percent(p.agreement)}
                    </span>
                    <Stack figures={p} />
                  </li>
                ))}
              </ul>
            </section>

            {data.reviewers?.length ? (
              <section className={styles.panel}>
                <h2>Reviewers</h2>
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Reviewer</th>
                        <th>Today</th>
                        <th>Labels</th>
                        <th>Calls</th>
                        <th>Per line</th>
                        <th>Agree</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.reviewers.map((reviewer) => (
                        <tr key={reviewer.email ?? "unknown"}>
                          <td>{reviewer.email ?? "Unknown"}</td>
                          <td>{reviewer.today}</td>
                          <td>{reviewer.labels}</td>
                          <td>{reviewer.calls_done}</td>
                          <td>
                            {reviewer.median_seconds != null
                              ? `${Math.round(reviewer.median_seconds)}s`
                              : "–"}
                          </td>
                          <td>{percent(reviewer.agreement)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
          </>
        )}
      </div>
    </AcquisitionShell>
  );
}
