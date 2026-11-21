"use client";

import {
  ChevronRight,
  Download,
  NotebookPen,
  PhoneCall,
  Route,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { displayName } from "../display-name";
import type { ActivityItem } from "../leads/leads-client";
import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import { Button, Skeleton } from "../ui/kit";
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

/**
 * sx-redesign board pick A "grouped cards" (owner, 21 Nov 2026): v1.90 Home
 * pills, solid deep green when chosen.
 */
function Pills<T extends string>({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: { key: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className={styles.pills} role="group" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className={styles.pill}
          aria-pressed={item.key === value}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

/** "+18%", "−5%", "New" or "Same", against the period before. */
function change(now: number, before: number): { words: string; tone: string } {
  if (now === before) return { words: "Same", tone: "flat" };
  if (before === 0) return { words: "New", tone: "up" };
  const percent = Math.round(((now - before) / before) * 100);
  if (percent === 0) return { words: "Same", tone: "flat" };
  return percent > 0
    ? { words: `+${count(percent)}%`, tone: "up" }
    : { words: `−${count(Math.abs(percent))}%`, tone: "down" };
}

/** "Priya Deshmukh" -> "PD". */
function letters(name: string): string {
  const words = name.split(/\s+/).filter((word) => /^\p{L}/u.test(word));
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? words[words.length - 1][0] : "";
  return `${first}${last}`.toUpperCase() || "·";
}

const TONES = ["emerald", "sky", "orange", "violet", "rose"] as const;
function toneOf(name: string): string {
  let sum = 0;
  for (const letter of name) sum = (sum * 31 + letter.charCodeAt(0)) >>> 0;
  return TONES[sum % TONES.length];
}

/** The hero's trend: the team's connected calls day by day, as one line. */
function Trend({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const width = 200,
    height = 64;
  const top = Math.max(1, ...values);
  const points = values.map((value, index) => [
    (index / (values.length - 1)) * width,
    height - 4 - (value / top) * (height - 8),
  ]);
  const line = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`);
  return (
    <svg
      className={styles.trend}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <polygon
        className={styles.trendFill}
        points={`0,${height} ${line.join(" ")} ${width},${height}`}
      />
      <polyline className={styles.trendLine} points={line.join(" ")} />
    </svg>
  );
}

const STAT_ICONS = {
  calls: PhoneCall,
  notes: NotebookPen,
  moves: Route,
} as const;

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
    <Pills<PeriodKey>
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
        <Skeleton height={168} />
        <div className={styles.stats}>
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} height={104} />
          ))}
        </div>
        <Skeleton height={420} />
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
  const label = METRICS.find((row) => row.key === metric)!.label.toLowerCase();
  const empty = data.currentComplete && data.currentWork === 0;
  const many = data.today > data.start;
  // The team's connected calls day by day (the hero's line and best day).
  const days_ = Array.from(
    { length: data.today - data.start + 1 },
    (_, index) =>
      data.people.reduce(
        (sum, person) => sum + (person.daily[index]?.conversations ?? 0),
        0,
      ),
  );
  const best = days_.reduce(
    (at, value, index) => (value > days_[at] ? index : at),
    0,
  );
  const compared = data.currentComplete && data.previousComplete;
  const opens = (key: Metric) => !initial && data.current[key] > 0;
  const heroValue = coveredCount(
    data.current.conversations,
    data.currentComplete,
  );
  const heroChange = change(
    data.current.conversations,
    data.previous.conversations,
  );
  const heroBody = (
    <>
      <span className={styles.heroHead}>
        <span className={styles.tile} data-tone="calls" aria-hidden="true">
          <PhoneCall size={20} strokeWidth={1.8} />
        </span>
        <span className={styles.heroWords}>
          <span className={styles.heroTitle}>Connected calls</span>
          <span className={styles.heroLine}>
            {many && days_[best] > 0
              ? `Best day: ${dayText(data.start + best)}`
              : "Calls that reached the lead"}
          </span>
        </span>
      </span>
      <span className={styles.heroNumbers}>
        <strong className={styles.heroValue}>{heroValue}</strong>
        {compared ? (
          <span className={styles.change} data-tone={heroChange.tone}>
            {heroChange.words}
          </span>
        ) : (
          <small className={styles.unknown}>Comparison unavailable</small>
        )}
        {many ? <Trend values={days_} /> : null}
      </span>
    </>
  );
  return (
    <section className={styles.page} aria-label="Calls and activity analytics">
      <header className={styles.header}>
        <div>
          <h2>{team ? "Team activity" : "Your activity"}</h2>
          <p>
            {data.today > data.start
              ? `Last ${data.today - data.start + 1} days · ${dayText(data.start)} – ${dayText(data.today)}`
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
      {/* The one hero: connected calls, its change and its line. Each number
          opens the list behind it; a fixture has no feed. */}
      {opens("conversations") ? (
        <button
          type="button"
          className={styles.hero}
          aria-label={`Conversations, ${heroValue}. See the list`}
          onClick={() => setList("conversations")}
        >
          {heroBody}
        </button>
      ) : (
        <div className={styles.hero}>{heroBody}</div>
      )}
      <div
        className={styles.stats}
        aria-label="This period versus previous period"
      >
        {(["calls", "notes", "moves"] as const).map((key) => {
          const row = METRICS.find((item) => item.key === key)!;
          const Icon = STAT_ICONS[key];
          const value = coveredCount(data.current[key], data.currentComplete);
          const moved = change(data.current[key], data.previous[key]);
          const body = (
            <>
              <span className={styles.statTop}>
                <span
                  className={styles.tile}
                  data-tone={key}
                  aria-hidden="true"
                >
                  <Icon size={18} strokeWidth={1.8} />
                </span>
                {compared ? (
                  <span className={styles.change} data-tone={moved.tone}>
                    {moved.words}
                  </span>
                ) : null}
              </span>
              <strong>{value}</strong>
              <span className={styles.statLabel}>{row.label}</span>
            </>
          );
          return opens(key) ? (
            <button
              key={key}
              type="button"
              className={styles.stat}
              aria-label={`${row.label}, ${value}. See the list`}
              onClick={() => setList(key)}
            >
              {body}
            </button>
          ) : (
            <div key={key} className={styles.stat}>
              {body}
            </div>
          );
        })}
      </div>
      <section className={styles.chart} aria-label="Activity by person">
        <div className={styles.chartHeader}>
          <span className={styles.tile} data-tone="people" aria-hidden="true">
            <Users size={20} strokeWidth={1.8} />
          </span>
          <div>
            <h3>
              {team
                ? `${label.charAt(0).toUpperCase() + label.slice(1)} by person`
                : "Your work"}
            </h3>
            <p>Same scale for everyone</p>
          </div>
        </div>
        <Pills<Metric>
          label="Compare activity"
          items={METRICS.map((row) => ({
            key: row.key,
            // Short names, so all four fit one line on a phone (bug 187).
            label:
              row.key === "conversations"
                ? "Connected"
                : row.key === "moves"
                  ? "Stages"
                  : row.label,
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
              const value = person.current[metric];
              const body = (
                <>
                  <span
                    className={styles.face}
                    data-tone={toneOf(person.name)}
                    aria-hidden="true"
                  >
                    {letters(person.name)}
                  </span>
                  <span className={styles.personMain}>
                    <span className={styles.personHead}>
                      <strong>{person.name}</strong>
                      <span className={styles.personValue}>
                        {coveredCount(value, data.currentComplete)}
                        {/* One call, not "1 calls" (10 Nov 2026). */}
                        <span className={styles.readerOnly}>
                          {" "}
                          {value === 1 ? label.replace(/s$/, "") : label}
                        </span>
                      </span>
                    </span>
                    <span className={styles.bar} aria-hidden="true">
                      <i style={{ width: `${(value / max) * 100}%` }} />
                    </span>
                    {metric === "calls" &&
                    person.current.calls === 0 &&
                    (person.current.notes > 0 || person.current.moves > 0) ? (
                      <small className={styles.otherWork}>
                        {coveredCount(
                          person.current.notes,
                          data.currentComplete,
                        )}{" "}
                        notes ·{" "}
                        {coveredCount(
                          person.current.moves,
                          data.currentComplete,
                        )}{" "}
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
                  </span>
                </>
              );
              // A teammate's People page is for those who see the team;
              // everyone opens their own.
              return (
                <li key={person.id ?? "unattributed"}>
                  {person.id && (team || person.id === personId) ? (
                    <Link
                      href={`/organisation/people/${encodeURIComponent(person.id)}`}
                      aria-label={`Open ${person.name}’s People page: ${coveredCount(value, data.currentComplete)} ${label}`}
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
          calls that connected. Compared with {dayText(data.prior)} –{" "}
          {dayText(data.start - 1)}.
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
