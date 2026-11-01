"use client";

import { ChevronRight, Download } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { displayName } from "../display-name";
import type { ActivityItem } from "../leads/leads-client";
import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import { Button, Segmented, Skeleton } from "../ui/kit";
import {
  activityCsv,
  activitySummary,
  countsToward,
  dayIso,
  dayNumber,
  dayText,
  METRICS,
  PERIODS,
  periodFrom,
  readActivityPage,
  readAnalytics,
  type AnalyticsHistory,
  type AnalyticsSummary,
  type Metric,
  type PeriodKey,
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
  const last = Math.max(1, values.length - 1);
  const path = values
    .map((value, index) =>
      value === null
        ? ""
        : `${index === 0 || values[index - 1] === null ? "M" : "L"}${2 + (index / last) * 112},${30 - (value / Math.max(1, peak)) * 27}`,
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

/** The period in the address (?days=), kept as the hub's other params are. */
function usePeriod(fixed: boolean) {
  const [period, setPeriod] = useState<PeriodKey>(() =>
    fixed || typeof window === "undefined"
      ? "30"
      : periodFrom(new URLSearchParams(window.location.search).get("days")),
  );
  const choose = (next: PeriodKey) => {
    setPeriod(next);
    const url = new URL(window.location.href);
    if (next === "30") url.searchParams.delete("days");
    else url.searchParams.set("days", next);
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  };
  return [period, choose] as const;
}

function download(data: AnalyticsSummary) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(
    new Blob([activityCsv(data)], { type: "text/csv" }),
  );
  link.download = `team-activity-${dayIso(data.start)}-to-${dayIso(data.today)}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
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
  const [period, setPeriod] = usePeriod(Boolean(initial));
  const days = PERIODS.find((item) => item.key === period)!.days;
  const [data, setData] = useState(initial ? activitySummary(initial) : null);
  const [metric, setMetric] = useState<Metric>("calls");
  const [all, setAll] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  // The list behind a number (competitor teardown 15, 1 Nov 2026).
  const [list, setList] = useState<Metric | null>(null);
  useEffect(() => {
    if (initial) return;
    const control = new AbortController();
    readAnalytics({ team, personId, days, signal: control.signal })
      .then((value) => {
        if (!control.signal.aborted) {
          setData(value);
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
  }, [team, personId, initial, attempt, days]);
  const chips = initial ? null : (
    <Segmented<PeriodKey>
      label="Period"
      items={PERIODS.map((item) => ({ key: item.key, label: item.label }))}
      value={period}
      onChange={setPeriod}
    />
  );
  if (!data)
    return (
      <section
        className={styles.page}
        aria-label="Loading activity"
        aria-busy={!failed}
      >
        <header className={styles.header}>
          <h2>{team ? "Team activity" : "Your activity"}</h2>
          {chips}
        </header>
        <div className={styles.summary}>
          {METRICS.map((row) => (
            <Skeleton key={row.key} height={95} />
          ))}
        </div>
        <Skeleton height={450} />
      </section>
    );
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
  // One day has no line to draw: the bars say it.
  const lines = data.today > data.start;
  const label = METRICS.find((row) => row.key === metric)!.label.toLowerCase();
  const empty = data.currentComplete && data.currentWork === 0;
  return (
    <section className={styles.page} aria-label="Calls and activity analytics">
      <header className={styles.header}>
        <div>
          <h2>{team ? "Team activity" : "Your activity"}</h2>
          <p>
            {data.today > data.start
              ? `Last ${data.today - data.start + 1} days · ${dayText(data.start)} – ${dayText(data.today)} · Today so far`
              : `Today so far · ${dayText(data.today)}`}
          </p>
        </div>
        <div className={styles.headerTools}>
          {chips ?? <span className={styles.period}>30 days</span>}
          {team && !initial && !empty ? (
            <Button
              variant="ghost"
              onClick={() => download(data)}
              aria-label="Export the period as a CSV file"
            >
              <Download size={15} aria-hidden="true" /> Export
            </Button>
          ) : null}
        </div>
      </header>
      <div
        className={styles.summary}
        aria-label="This period versus previous period"
      >
        {METRICS.map((row) => {
          const delta = data.current[row.key] - data.previous[row.key];
          const value = coveredCount(
            data.current[row.key],
            data.currentComplete,
          );
          const body = (
            <>
              <span>{row.label}</span>
              <strong>{value}</strong>
              <small>
                {data.currentComplete && data.previousComplete
                  ? `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${count(Math.abs(delta))} vs ${count(data.previous[row.key])} prior`
                  : "Comparison unavailable"}
              </small>
            </>
          );
          // Each number opens the list behind it; a fixture has no feed.
          return initial || data.current[row.key] === 0 ? (
            <div key={row.key}>{body}</div>
          ) : (
            <button
              key={row.key}
              type="button"
              aria-label={`${row.label}, ${value}. See the list`}
              onClick={() => setList(row.key)}
            >
              {body}
            </button>
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
                    {lines ? (
                      <Sparkline
                        values={daily}
                        peak={peak}
                        label={chartLabel}
                      />
                    ) : null}
                  </div>
                </>
              );
              // A teammate's People page is for those who see the team;
              // everyone opens their own.
              return (
                <li key={person.id ?? "unattributed"}>
                  {person.id && (team || person.id === personId) ? (
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
                {lines ? (
                  <>
                    <br />
                    Daily activity: 0–{count(peak)} updates per day
                  </>
                ) : null}
              </span>
              <span>
                {lines
                  ? `${dayText(data.start)} → ${dayText(data.today)}`
                  : dayText(data.today)}
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
        {/* In plain words (Dipak's walk, ph1-21, 1 Nov 2026: the footnotes
            read like code, a time zone's id among them). */}
        <p>
          {team ? "Your team's work" : "Your work"} in {zoneName(data.timezone)}
          . Calls count every call, with a report or not; conversations are the
          calls that connected. The daily lines count notes and stage moves too.
        </p>
        <p>
          Compared with {dayText(data.prior)} – {dayText(data.start - 1)}.
          {!data.currentComplete || !data.previousComplete
            ? " Some older days haven't loaded yet: a number with + is at least that many, and — means not known yet."
            : ""}
          {data.directoryMissing
            ? " The team list didn't load, so only people with recorded work are shown."
            : ""}
        </p>
      </footer>
      <ActivityList
        metric={list}
        data={data}
        days={days}
        team={team}
        personId={personId}
        onClose={() => setList(null)}
      />
    </section>
  );
}

/** Enough rows to fill a phone's sheet before "Show more". */
const LIST_PAGE = 30;

const TIME = new Intl.DateTimeFormat("en-IN", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
const DAY_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

/** What happened, in a few words: "Connected · 3 min", "Moved to Interested". */
function whatHappened(item: ActivityItem): string {
  const event = item.event;
  if (event.kind === "call") {
    const seconds = event.duration_seconds ?? 0;
    if (event.connected === true || seconds > 0)
      return seconds >= 60
        ? `Connected · ${Math.round(seconds / 60)} min`
        : "Connected";
    return "Not connected";
  }
  if (event.kind === "note") return event.note?.trim() || "Note";
  return event.stage_label ? `Moved to ${event.stage_label}` : "Stage moved";
}

/**
 * The list behind a number: the period's calls, conversations, notes or stage
 * moves, newest first, each opening its lead (competitor teardown 15). Read
 * from the same feed the summary counts, page by page, until the period's
 * first day.
 */
function ActivityList({
  metric,
  data,
  days,
  team,
  personId,
  onClose,
}: {
  metric: Metric | null;
  data: AnalyticsSummary;
  days: number;
  team: boolean;
  personId?: string;
  onClose: () => void;
}) {
  // The rows belong to the number and period they were read for; another
  // number shows as loading until its own arrive.
  const opened = metric
    ? `${metric}:${days}:${data.start}:${data.today}`
    : null;
  const [loaded, setLoaded] = useState<{
    for: string;
    rows: ActivityItem[];
  } | null>(null);
  const rows = loaded && loaded.for === opened ? loaded.rows : null;
  // So does how its reading went: a list not read yet is loading.
  const [status, setStatus] = useState<{
    for: string;
    state: "more" | "done" | "loading" | "failed";
  } | null>(null);
  const state = status && status.for === opened ? status.state : "loading";
  const cursor = useRef<string | null>(null);
  const round = useRef(0);

  /** Reads the list (fresh) or its next rows; nothing changes until a page arrives. */
  const fill = useCallback(
    async (fresh: boolean) => {
      if (!metric || !opened) return;
      const id = fresh ? ++round.current : round.current;
      const target = opened;
      const found: ActivityItem[] = [];
      try {
        for (let page = 0; page < 20 && found.length < LIST_PAGE; page += 1) {
          const answer = await readActivityPage({
            days,
            team,
            personId,
            before: cursor.current,
          });
          if (id !== round.current) return;
          let past = false;
          for (const item of answer.items) {
            if (dayNumber(item.event.at, data.timezone) < data.start) {
              past = true;
              break;
            }
            if (countsToward(metric, item.event)) found.push(item);
          }
          cursor.current = answer.next_before;
          if (past || !answer.next_before) {
            cursor.current = null;
            break;
          }
        }
        setLoaded((current) => ({
          for: target,
          rows: [
            ...(fresh || current?.for !== target ? [] : current.rows),
            ...found,
          ],
        }));
        setStatus({ for: target, state: cursor.current ? "more" : "done" });
      } catch {
        if (id !== round.current) return;
        setStatus({ for: target, state: "failed" });
      }
    },
    [data.start, data.timezone, days, metric, opened, personId, team],
  );

  // A tap (Show more, Try again) shows its loading at once.
  const tap = (fresh: boolean) => {
    if (opened) setStatus({ for: opened, state: "loading" });
    void fill(fresh);
  };

  // Each opening reads afresh, and so does a new period or scope.
  useEffect(() => {
    if (!metric) return;
    cursor.current = null;
    // Read once the effect is done: nothing is set while it runs.
    void Promise.resolve().then(() => fill(true));
  }, [metric, fill]);

  const title = metric
    ? `${METRICS.find((row) => row.key === metric)!.label} · ${
        days === 1 ? "today" : `last ${days} days`
      }`
    : "Activity";
  const today = data.today;
  return (
    <Sheet
      open={metric !== null}
      onClose={() => {
        round.current += 1;
        onClose();
      }}
      title={title}
      description={
        metric
          ? `${count(data.current[metric])} in all${team ? ", the whole team" : ""}`
          : undefined
      }
    >
      {rows === null ? (
        state === "failed" ? (
          <div className={styles.listEnd}>
            <p>The list didn’t load.</p>
            <Button onClick={() => tap(true)}>Try again</Button>
          </div>
        ) : (
          <div className={styles.listLoading} aria-busy="true">
            <Skeleton height={56} />
            <Skeleton height={56} />
            <Skeleton height={56} />
          </div>
        )
      ) : (
        <>
          {rows.length ? (
            <ul className={styles.list}>
              {rows.map((item) => {
                const at = new Date(item.event.at);
                const when =
                  dayNumber(item.event.at, data.timezone) === today
                    ? TIME.format(at)
                    : DAY_TIME.format(at);
                return (
                  <li key={item.event_id}>
                    <Link
                      href={`/leads#lead=${encodeURIComponent(item.lead_id)}`}
                    >
                      <span className={styles.listText}>
                        <strong>{displayName(item.lead_name)}</strong>
                        <small>
                          {[
                            team && item.event.actor_name
                              ? displayName(item.event.actor_name)
                              : null,
                            whatHappened(item),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </small>
                      </span>
                      <time dateTime={item.event.at}>{when}</time>
                      <ChevronRight size={16} aria-hidden="true" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : state === "done" ? (
            <p className={styles.listEnd}>
              None to show: private calls stay with their sellers.
            </p>
          ) : null}
          {state === "more" ? (
            <Button onClick={() => tap(false)}>Show more</Button>
          ) : state === "loading" ? (
            <Skeleton height={44} />
          ) : state === "failed" ? (
            <div className={styles.listEnd}>
              <p>More didn’t load.</p>
              <Button onClick={() => tap(false)}>Try again</Button>
            </div>
          ) : null}
        </>
      )}
    </Sheet>
  );
}

/** "India Standard Time" for Asia/Kolkata: a zone in words, not its id. */
function zoneName(zone: string): string {
  try {
    const part = new Intl.DateTimeFormat("en-IN", {
      timeZone: zone,
      timeZoneName: "long",
    })
      .formatToParts(new Date())
      .find((item) => item.type === "timeZoneName");
    return part?.value ?? "your time zone";
  } catch {
    return "your time zone";
  }
}
