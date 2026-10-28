"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { notify } from "../notice-center";
import { Button, Segmented, Skeleton } from "../ui/kit";
import {
  activitySummary,
  dayText,
  METRICS,
  readAnalytics,
  type AnalyticsHistory,
  type Metric,
} from "./analytics-data";
import styles from "./analytics.module.css";
const count = (value: number) => value.toLocaleString("en-IN");

const coveredCount = (value: number, complete: boolean) =>
  !complete && value === 0 ? "—" : `${count(value)}${complete ? "" : "+"}`;

function Sparkline({
  values,
  peak,
  label,
}: {
  values: (number | null)[];
  peak: number;
  label: string;
}) {
  // Gaps remain gaps. Every person uses the same daily scale.
  const path = values
    .map((value, index) =>
      value === null
        ? ""
        : `${index === 0 || values[index - 1] === null ? "M" : "L"}${2 + (index / 29) * 112},${30 - (value / Math.max(1, peak)) * 27}`,
    )
    .join(" ");
  return (
    <svg
      className={styles.spark}
      viewBox="0 0 116 34"
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      <path className={styles.baseline} d="M2 30H114" />
      <path d={path} />
    </svg>
  );
}
export function AnalyticsView({
  team,
  personId,
  initial,
}: {
  team: boolean;
  personId?: string;
  initial?: AnalyticsHistory;
}) {
  const [history, setHistory] = useState(initial ?? null);
  const [metric, setMetric] = useState<Metric>("calls");
  const [all, setAll] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const moreControl = useRef<AbortController | null>(null);
  useEffect(() => () => moreControl.current?.abort(), []);
  useEffect(() => {
    if (initial) return;
    const control = new AbortController();
    readAnalytics({ team, personId, signal: control.signal })
      .then((value) => {
        if (!control.signal.aborted) {
          setHistory(value);
          setFailed(false);
        }
      })
      .catch(() => {
        if (control.signal.aborted) return;
        setFailed(true);
        notify({
          id: "analytics-read",
          tone: "error",
          title: "Activity didn't load",
          action: {
            label: "Try again",
            run: () => {
              setFailed(false);
              setAttempt((n) => n + 1);
            },
          },
        });
      });
    return () => control.abort();
  }, [team, personId, initial, attempt]);
  const loadMore = async () => {
    if (!history || busy) return;
    setBusy(true);
    const control = new AbortController();
    moreControl.current = control;
    try {
      const value = await readAnalytics({
        team,
        personId,
        previous: history,
        signal: control.signal,
      });
      if (!control.signal.aborted) setHistory(value);
    } catch {
      if (control.signal.aborted) return;
      notify({
        id: "analytics-more",
        tone: "error",
        title: "More activity didn't load. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  if (!history)
    return (
      <section
        className={styles.page}
        aria-label="Loading activity"
        aria-busy={!failed}
      >
        <h2>Team activity</h2>
        <div className={styles.summary}>
          {METRICS.map((row) => (
            <Skeleton key={row.key} height={95} />
          ))}
        </div>
        <Skeleton height={450} />
        {failed ? (
          <Button
            onClick={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </Button>
        ) : null}
      </section>
    );
  const data = activitySummary(history);
  const sorted = [...data.people].sort(
    (a, b) =>
      b.current[metric] - a.current[metric] ||
      b.work - a.work ||
      a.name.localeCompare(b.name),
  );
  const rows = all ? sorted : sorted.slice(0, 7);
  const max = Math.max(1, ...sorted.map((row) => row.current[metric]));
  const peak = Math.max(
    1,
    ...sorted.flatMap((row) => row.daily.map((day) => day?.work ?? 0)),
  );
  const label = METRICS.find((row) => row.key === metric)!.label.toLowerCase();
  const empty = data.currentComplete && data.currentWork === 0;
  return (
    <section className={styles.page} aria-label="Calls and activity analytics">
      <header className={styles.header}>
        <div>
          <h2>{team ? "Team activity" : "Your activity"}</h2>
          <p>
            Last 30 days · {dayText(data.start)} – {dayText(data.today)} · Today
            so far
          </p>
        </div>
        <span className={styles.period}>30 days</span>
      </header>
      <div
        className={styles.summary}
        aria-label="This period versus previous period"
      >
        {METRICS.map((row) => {
          const delta = data.current[row.key] - data.previous[row.key];
          return (
            <div key={row.key}>
              <span>{row.label}</span>
              <strong>
                {coveredCount(data.current[row.key], data.currentComplete)}
              </strong>
              <small>
                {data.currentComplete && data.previousComplete
                  ? `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${count(Math.abs(delta))} vs ${count(data.previous[row.key])} prior`
                  : "Comparison unavailable"}
              </small>
            </div>
          );
        })}
      </div>
      <section className={styles.chart} aria-label="Activity by person">
        <div className={styles.chartHeader}>
          <h3>{team ? "Who’s been active?" : "Your work, day by day"}</h3>
          <p>
            {label.charAt(0).toUpperCase() + label.slice(1)} by person · Same
            scale
          </p>
        </div>
        <Segmented<Metric>
          label="Compare activity"
          items={METRICS.map((row) => ({
            key: row.key,
            label: row.key === "conversations" ? "Connected" : row.label,
          }))}
          value={metric}
          onChange={setMetric}
        />
        {empty ? (
          <div className={styles.empty}>
            <h3>No activity recorded this period</h3>
            <p>
              Calls, messages, notes and stage moves appear as your team works
              leads.
            </p>
            <Link className={styles.action} href="/leads">
              Open leads
            </Link>
          </div>
        ) : null}
        {empty ? null : !rows.length ? (
          <p className={styles.empty}>
            No people available in the loaded history.
          </p>
        ) : (
          <ul
            className={styles.people}
            aria-label={`People sorted by ${label}`}
          >
            {rows.map((person) => {
              const daily = person.daily.map((day) => day?.work ?? null);
              const chartLabel = `${person.name}: daily activity updates, ${daily.map((n, index) => `${dayText(data.start + index)}: ${n === null ? "unavailable" : n}`).join("; ")}`;
              const body = (
                <>
                  <div className={styles.personHead}>
                    <strong>{person.name}</strong>
                    <span>
                      {coveredCount(
                        person.current[metric],
                        data.currentComplete,
                      )}{" "}
                      {label}
                    </span>
                  </div>
                  {metric === "calls" &&
                  person.current.calls === 0 &&
                  (person.current.notes > 0 || person.current.moves > 0) ? (
                    <small className={styles.otherWork}>
                      {coveredCount(person.current.notes, data.currentComplete)}{" "}
                      notes ·{" "}
                      {coveredCount(person.current.moves, data.currentComplete)}{" "}
                      stage moves
                    </small>
                  ) : null}
                  {metric === "calls" &&
                  person.current.calls === 0 &&
                  person.current.notes === 0 &&
                  person.current.moves === 0 &&
                  person.work > 0 ? (
                    <small className={styles.otherWork}>
                      Other updates:{" "}
                      {coveredCount(person.work, data.currentComplete)}
                    </small>
                  ) : null}
                  <div className={styles.visualRow}>
                    <span className={styles.bar} aria-hidden="true">
                      <i
                        style={{
                          width: `${(person.current[metric] / max) * 100}%`,
                        }}
                      />
                    </span>
                    <Sparkline values={daily} peak={peak} label={chartLabel} />
                  </div>
                </>
              );
              return (
                <li key={person.id ?? "unattributed"}>
                  {person.id ? (
                    <Link
                      href={`/organisation/people/${encodeURIComponent(person.id)}`}
                      aria-label={`Open ${person.name}’s People page: ${coveredCount(person.current[metric], data.currentComplete)} ${label}`}
                    >
                      {body}
                    </Link>
                  ) : (
                    <div>{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {!empty ? (
          <>
            <div className={styles.chartFoot}>
              <span>
                Bars: 0–{count(max)} {label}
                <br />
                Daily activity: 0–{count(peak)} updates per day
              </span>
              <span>
                {dayText(data.start)} → {dayText(data.today)}
              </span>
            </div>
          </>
        ) : null}
        {!empty && sorted.length > 7 ? (
          <Button aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `Show all (${sorted.length})`}
          </Button>
        ) : null}
      </section>
      <footer className={styles.coverage}>
        <p>
          {team ? "Visible team work" : "Your visible work"} ·{" "}
          {history.timezone} · Calls include those without reports.
          Conversations are connected calls. Daily lines include other recorded
          work.
        </p>
        <p>
          Prior: {dayText(data.prior)} – {dayText(data.start - 1)}.
          {!data.currentComplete || !data.previousComplete
            ? " Partial history: + means at least; — and gaps are unavailable."
            : " Full period history loaded."}
          {data.directoryMissing
            ? " People list unavailable; showing people with recorded work."
            : ""}
        </p>
        {!data.previousComplete ? (
          <Button disabled={busy} onClick={() => void loadMore()}>
            {busy ? "Loading…" : "Load older activity"}
          </Button>
        ) : null}
      </footer>
    </section>
  );
}
