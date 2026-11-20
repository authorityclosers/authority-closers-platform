"use client";

/**
 * The owner's Home, Team (round 2, board 6 "Owner analytics", option A
 * "Briefing first", 20 Nov 2026): "is work happening?" answered at a glance.
 *
 * 1. Plain-language insights, worst first, each with one action.
 * 2. Today's figures beside the same weekday last week.
 * 3. One row per seller: now, calls, connected, talk, speed to lead, calls
 *    with no recording, late follow-ups.
 * 4. What is coming, said plainly as coming (the board's table: tiles that
 *    need new reports or new data show "coming soon" until built).
 *
 * Every number comes from the Performance engine and is counted by
 * team-numbers.ts, as Growth's are, so Home and Growth agree; All leads
 * unless Inbound is picked, and each number says which. On a phone the same
 * page is the glance: the key figures, the insights, the sellers' list.
 */

import {
  AlertTriangle,
  ChevronRight,
  Clock,
  PhoneMissed,
  Sparkles,
  Timer,
  UserPlus,
} from "lucide-react";
import Link from "next/link";
import { useSyncExternalStore, type ReactNode } from "react";

import { displayName } from "../display-name";
import { deskRequest, type LeadPage } from "../leads/leads-client";
import {
  readEffort,
  type Effort,
  type SellerEffort,
} from "../performance/performance-client";
import { dayName, noonOf, shiftDay, useHomeDay } from "./home-day";
import { breakLength } from "./home-today";
import { useHomeRead } from "./home-load";
import { CLOCK, DAY, useMinute, waited } from "./queue-words";
import { leadsHref } from "./seller-home";
import { talkOrDash } from "./talk-time";
import { noCallsNote, talkShort, type StageKeys } from "./team-floor";
import {
  SCOPE_WORDS,
  sellerFigures,
  teamFigures,
  type DayFigures,
  type Scope,
} from "./team-numbers";
import styles from "./team-today.module.css";

const IST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });
const WEEKDAY = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  timeZone: "Asia/Kolkata",
});
const IST_HOUR = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  hourCycle: "h23",
  timeZone: "Asia/Kolkata",
});

/** An hour or more since the last call, inside the day: worth a word. */
const LONG_GAP_MINUTES = 60;

/** The same weekday a week ago, India time ("2026-11-13"). */
export const weekAgo = (now: Date) =>
  IST_DATE.format(new Date(now.getTime() - 7 * 86_400_000));

const SCOPE_EVENT = "sx:team-scope";
const readScope = (): Scope =>
  new URLSearchParams(window.location.search).get("count") === "inbound"
    ? "inbound"
    : "all";
const onScope = (change: () => void) => {
  window.addEventListener("popstate", change);
  window.addEventListener(SCOPE_EVENT, change);
  return () => {
    window.removeEventListener("popstate", change);
    window.removeEventListener(SCOPE_EVENT, change);
  };
};

/** All leads or Inbound, kept in the address so Back and a refresh keep it. */
function useScope(): [Scope, (next: Scope) => void] {
  const scope = useSyncExternalStore<Scope>(onScope, readScope, () => "all");
  return [
    scope,
    (next) => {
      const params = new URLSearchParams(window.location.search);
      if (next === "inbound") params.set("count", "inbound");
      else params.delete("count");
      const query = params.toString();
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}`,
      );
      window.dispatchEvent(new Event(SCOPE_EVENT));
    },
  ];
}

const first = (name: string) => displayName(name).split(" ")[0];
const plural = (count: number, one: string, many: string) =>
  `${count} ${count === 1 ? one : many}`;

/** Minutes since a seller's last call, or null with no call today. */
const quietFor = (seller: SellerEffort, now: Date): number | null =>
  seller.last_call_at
    ? (now.getTime() - Date.parse(seller.last_call_at)) / 60_000
    : null;

export type SellerNow = {
  words: string;
  tone: "calling" | "quiet" | "none";
};

/** Where a seller is now, from the last call: the phone app doesn't say live
 *  whether a call is on, so this never claims one (board 6: "needs new data"). */
export function sellerNow(
  seller: SellerEffort,
  scope: Scope,
  now: Date,
  /** A past day: its last call, never a gap that runs to now. */
  past = false,
): SellerNow {
  const calls = sellerFigures(seller, scope).calls;
  const quiet = quietFor(seller, now);
  if (!calls || quiet === null) return { words: "No calls yet", tone: "none" };
  if (!past && quiet >= LONG_GAP_MINUTES)
    return {
      words: `No call for ${breakLength(Math.floor(quiet))}`,
      tone: "quiet",
    };
  return {
    words: `Last call ${CLOCK.format(new Date(seller.last_call_at as string))}`,
    tone: "calling",
  };
}

export type Insight = {
  key: string;
  tone: "bad" | "warn" | "good";
  text: string;
  action: { label: string; href: string };
};

const top = (
  sellers: SellerEffort[],
  value: (seller: SellerEffort) => number,
) => [...sellers].sort((a, b) => value(b) - value(a))[0];

/**
 * The morning note: rules over the day's numbers, worst first, each naming
 * what to do. Names are shown (the owner sees every seller's row anyway);
 * whether insights should name sellers is the owner's to decide (board 6).
 */
export function insights({
  today,
  before,
  scope,
  waiting,
  newKey,
  now,
  past = false,
}: {
  today: Effort;
  before: Effort | null;
  scope: Scope;
  /** New Inbound leads waiting for a first call, team-wide; null if unknown. */
  waiting: number | null;
  newKey: string | null;
  now: Date;
  /** A past day: no "hasn't called for an hour", which is about now. */
  past?: boolean;
}): Insight[] {
  const day = teamFigures(today, scope);
  const list: Insight[] = [];
  if (day.notCalledBack > 0)
    list.push({
      key: "missed",
      tone: "bad",
      text: `${plural(day.notCalledBack, "customer", "customers")} called and ${day.notCalledBack === 1 ? "hasn't" : "haven't"} been called back yet.`,
      action: {
        label: "See who",
        href: leadsHref("inbound", { view: "to_call" }),
      },
    });
  if (day.noRecording > 0) {
    const worst = top(
      today.sellers,
      (s) => sellerFigures(s, scope).noRecording,
    );
    const theirs = worst ? sellerFigures(worst, scope).noRecording : 0;
    const one = worst && day.noRecording >= 3 && theirs * 2 >= day.noRecording;
    list.push({
      key: "recordings",
      tone: "bad",
      text: one
        ? `${plural(day.noRecording, "connected call", "connected calls")} today ${day.noRecording === 1 ? "has" : "have"} no recording, ${theirs} from ${displayName(worst.name)}'s phone. Their phone setup may be off.`
        : `${plural(day.noRecording, "connected call", "connected calls")} today ${day.noRecording === 1 ? "has" : "have"} no recording yet.`,
      action: one
        ? {
            label: `See ${first(worst.name)}'s calls`,
            href: `/analysis/calls?day=today&person=${encodeURIComponent(worst.person_id)}`,
          }
        : { label: "See the calls", href: "/analysis/calls?day=today&team=1" },
    });
  }
  if (waiting && waiting > 0)
    list.push({
      key: "waiting",
      tone: "warn",
      text: `${plural(waiting, "new lead is", "new leads are")} waiting for a first call.`,
      action: {
        label: "See them",
        href: leadsHref("inbound", {
          view: "to_call",
          ...(newKey ? { step: newKey } : {}),
        }),
      },
    });
  // Quiet sellers count inside the working day only: not before 11 or after 8.
  const hour = Number(IST_HOUR.format(now));
  if (!past && hour >= 11 && hour < 20) {
    const quiet = today.sellers.filter((seller) => {
      const gap = quietFor(seller, now);
      const calls = sellerFigures(seller, "all").calls;
      return !calls || (gap !== null && gap >= LONG_GAP_MINUTES);
    });
    if (quiet.length === 1) {
      const seller = quiet[0];
      const gap = quietFor(seller, now);
      list.push({
        key: "quiet",
        tone: "warn",
        text:
          sellerFigures(seller, "all").calls && gap !== null
            ? `${displayName(seller.name)} hasn't made a call for ${breakLength(Math.floor(gap))}.`
            : `${displayName(seller.name)} hasn't made a call today.`,
        action: { label: "See the day", href: "/growth" },
      });
    } else if (quiet.length > 1)
      list.push({
        key: "quiet",
        tone: "warn",
        text: `${quiet.length} sellers haven't made a call for an hour or more: ${quiet
          .slice(0, 3)
          .map((seller) => first(seller.name))
          .join(
            ", ",
          )}${quiet.length > 3 ? ` and ${quiet.length - 3} more` : ""}.`,
        action: { label: "See the day", href: "/growth" },
      });
  }
  if (day.late > 0) {
    const worst = top(today.sellers, (s) => sellerFigures(s, scope).late);
    const theirs = worst ? sellerFigures(worst, scope).late : 0;
    list.push({
      key: "late",
      tone: "warn",
      text: `${plural(day.late, "follow-up is", "follow-ups are")} late${worst && theirs && today.sellers.length > 1 ? `, ${theirs} of them ${displayName(worst.name)}'s` : ""}.`,
      action: { label: "See late follow-ups", href: "/leads?tab=all&due=late" },
    });
  }
  if (day.speed !== null) {
    const was = before ? before.inbound.first_call_minutes : null;
    const weekday = WEEKDAY.format(new Date(now.getTime() - 7 * 86_400_000));
    const words =
      was === null
        ? ""
        : day.speed < was
          ? `, faster than the ${weekday} before (${waited(Math.round(was))})`
          : day.speed > was
            ? `, slower than the ${weekday} before (${waited(Math.round(was))})`
            : `, as the ${weekday} before`;
    list.push({
      key: "speed",
      tone: was !== null && day.speed > was ? "warn" : "good",
      text: `New leads were called in ${waited(Math.round(day.speed))}${past ? "" : " today"} (median)${words}.`,
      action: { label: "See Growth", href: "/growth" },
    });
  }
  return list.slice(0, 4);
}

function Kpi({
  label,
  value,
  note,
  href,
  primary = false,
}: {
  label: string;
  value: string;
  note: ReactNode;
  href: string;
  /** Kept on the phone's glance; the rest wait for a wider screen. */
  primary?: boolean;
}) {
  return (
    <li data-primary={primary || undefined}>
      <Link className={styles.kpi} href={href} data-sx-feature="team_kpi_open">
        <span className={styles.kpiLabel}>{label}</span>
        <strong>{value}</strong>
        <span className={styles.kpiNote}>{note}</span>
      </Link>
    </li>
  );
}

const minutesOr = (value: number | null, none = "None yet") =>
  value === null ? none : waited(Math.round(value));

function Figures({
  day,
  was,
  weekday,
  working,
  sellers,
  noCalls,
}: {
  day: DayFigures;
  was: DayFigures | null;
  weekday: string;
  working: number;
  sellers: number;
  /** Inbound picked and no Inbound calls: where today's calls are. */
  noCalls: string | null;
}) {
  const last = (value: string) => `Last ${weekday}: ${value}`;
  // As Growth writes it: 5 h 40 min.
  const talk = (figures: DayFigures) =>
    talkOrDash(figures.talkSeconds, figures.talkEstimatedSeconds, (seconds) =>
      breakLength(Math.round(seconds / 60)),
    );
  return (
    <ul className={styles.kpis} aria-label="Today's figures">
      <Kpi
        primary
        label="Sellers calling"
        value={`${working} of ${sellers}`}
        note="made a call today"
        href="/growth"
      />
      <Kpi
        primary
        label="Calls"
        value={String(day.calls)}
        note={noCalls ?? (was ? last(String(was.calls)) : "Today")}
        href="/analysis/calls?day=today&team=1"
      />
      <Kpi
        label="Connected"
        value={String(day.connected)}
        note={
          day.calls
            ? `${Math.round((day.connected / day.calls) * 100)}% of calls`
            : was
              ? last(String(was.connected))
              : "Today"
        }
        href="/analysis/calls?day=today&team=1&outcome=connected"
      />
      <Kpi
        label="Talk time"
        value={talk(day)}
        note={was ? last(talk(was)) : "Today"}
        href="/analysis/calls?sort=longest"
      />
      <Kpi
        primary
        label="Speed to lead"
        value={minutesOr(day.speed)}
        note={was ? last(minutesOr(was.speed, "none")) : "Inbound, median"}
        href="/growth"
      />
      <Kpi
        label="No recording"
        value={String(day.noRecording)}
        note="Connected calls"
        href="/analysis/calls?day=today&team=1"
      />
      <Kpi
        label="Late follow-ups"
        value={String(day.late)}
        note="Now"
        href="/leads?tab=all&due=late"
      />
    </ul>
  );
}

function Sellers({
  effort,
  scope,
  now,
  title,
}: {
  effort: Effort;
  scope: Scope;
  now: Date;
  /** "today", or the past day picked. */
  title: string;
}) {
  const rows = [...effort.sellers].sort(
    (a, b) => sellerFigures(b, scope).calls - sellerFigures(a, scope).calls,
  );
  if (!rows.length)
    return <p className={styles.quiet}>No sellers in this team yet.</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className={styles.caption}>
          {`Each seller ${title === "today" ? "today" : `on ${title}`} · ${SCOPE_WORDS[scope]}`}
        </caption>
        <thead>
          <tr>
            <th scope="col">Seller</th>
            <th scope="col" data-wide="">
              Now
            </th>
            <th scope="col">Calls</th>
            <th scope="col" data-wide="">
              Connected
            </th>
            <th scope="col" data-wide="">
              Talk
            </th>
            <th scope="col">Speed to lead</th>
            <th scope="col" data-wide="">
              No recording
            </th>
            <th scope="col" data-wide="">
              Late follow-ups
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((seller) => {
            const day = sellerFigures(seller, scope);
            const state = sellerNow(seller, scope, now, title !== "today");
            return (
              <tr key={seller.person_id} data-seller={seller.person_id}>
                <th scope="row">
                  <Link
                    className={styles.who}
                    href={`/analysis/calls?day=today&person=${encodeURIComponent(seller.person_id)}`}
                    data-sx-feature="team_seller_open"
                  >
                    <span className={styles.dot} data-tone={state.tone} />
                    <span className={styles.whoWords}>
                      <strong>{displayName(seller.name)}</strong>
                      <small data-tone={state.tone}>{state.words}</small>
                    </span>
                  </Link>
                </th>
                <td data-wide="">
                  <span data-tone={state.tone}>{state.words}</span>
                </td>
                <td>{day.calls}</td>
                <td data-wide="">{day.connected}</td>
                <td data-wide="">
                  {talkOrDash(
                    day.talkSeconds,
                    day.talkEstimatedSeconds,
                    talkShort,
                  )}
                </td>
                <td>
                  {day.speed === null ? "–" : waited(Math.round(day.speed))}
                </td>
                <td data-wide="" data-warn={day.noRecording > 0 || undefined}>
                  {day.noRecording}
                </td>
                <td data-wide="" data-warn={day.late > 0 || undefined}>
                  {day.late}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const TONE_ICON = {
  bad: AlertTriangle,
  warn: Clock,
  good: Sparkles,
} as const;

function Insights({ list }: { list: Insight[] | null }) {
  if (list === null)
    return (
      <ul className={styles.insights} aria-busy="true">
        {[0, 1].map((index) => (
          <li key={index} className={styles.wait} aria-hidden="true" />
        ))}
      </ul>
    );
  if (!list.length)
    return (
      <p className={styles.allClear}>
        <Sparkles size={18} aria-hidden="true" />
        Nothing needs you right now. All clear.
      </p>
    );
  return (
    <ul className={styles.insights} aria-label="What needs you">
      {list.map((insight) => {
        const Icon = TONE_ICON[insight.tone];
        return (
          <li
            key={insight.key}
            className={styles.insight}
            data-tone={insight.tone}
            data-insight={insight.key}
          >
            <Icon size={18} aria-hidden="true" />
            <p>{insight.text}</p>
            <Link
              className={styles.insightGo}
              href={insight.action.href}
              data-sx-feature="team_insight_action"
            >
              {insight.action.label}
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Tiles the board lists as needing new reports or data: named, not faked. */
const COMING = [
  "Leads untouched for 30 min, per seller",
  "Lead split: target against actual",
  "Hand-overs and their reasons",
  "Call score per seller",
  "On a call right now",
];

function ScopeSwitch({
  value,
  onChange,
}: {
  value: Scope;
  onChange: (next: Scope) => void;
}) {
  return (
    <div className={styles.scope} role="radiogroup" aria-label="What to count">
      {(["all", "inbound"] as const).map((key) => (
        <button
          key={key}
          type="button"
          role="radio"
          aria-checked={value === key}
          data-sx-feature="team_scope"
          onClick={() => onChange(key)}
        >
          {key === "all" ? "All leads" : "Inbound"}
        </button>
      ))}
    </div>
  );
}

export function TeamToday({
  stages,
  controls = null,
  more,
}: {
  stages?: StageKeys;
  /** Team controls behind their button, for those who manage leads. */
  controls?: ReactNode;
  /** The ways on, told how many sellers there are. */
  more?: (sellers: number) => ReactNode;
}) {
  const [scope, setScope] = useScope();
  const clock = useMinute();
  // A past day picked on Home's date: that whole day, beside the week before.
  const [picked] = useHomeDay();
  const now = picked ? new Date(`${picked}T23:59:00+05:30`) : clock;
  const ago = picked ? shiftDay(picked, -7) : weekAgo(now);
  const today = useHomeRead<Effort>(
    picked ? `effort:1:${picked}` : "effort:1",
    (signal) => readEffort(1, signal, false, picked ?? undefined),
  );
  const before = useHomeRead<Effort>(`effort:1:${ago}`, (signal) =>
    readEffort(1, signal, false, ago),
  );
  const newKey = stages?.newKey ?? null;
  const waiting = useHomeRead<number | null>(
    `team-waiting:${newKey ?? "-"}`,
    async (signal) =>
      newKey
        ? (
            await deskRequest<LeadPage>(
              `/leads?scope=team&side=inbound&view=to_call&step=${encodeURIComponent(newKey)}`,
              { signal },
            )
          ).total
        : null,
  );
  const effort = today.value;
  const day = effort ? teamFigures(effort, scope) : null;
  const was = before.value ? teamFigures(before.value, scope) : null;
  const weekday = WEEKDAY.format(noonOf(ago));
  const working = effort
    ? effort.sellers.filter((seller) => sellerFigures(seller, scope).calls > 0)
        .length
    : 0;
  return (
    <div className={styles.page} data-team-today="">
      <header className={styles.header}>
        <div className={styles.title}>
          <h2>{picked ? `Team on ${dayName(picked)}` : "Team today"}</h2>
          <p>
            {picked
              ? `The whole day · ${SCOPE_WORDS[scope]}`
              : `${DAY.format(now)} · ${CLOCK.format(now)} · ${SCOPE_WORDS[scope]}`}
          </p>
        </div>
        <div className={styles.tools}>
          <ScopeSwitch value={scope} onChange={setScope} />
          {controls}
        </div>
      </header>

      <section aria-labelledby="insights-title" className={styles.section}>
        <h3 id="insights-title" className={styles.sectionTitle}>
          What needs you
        </h3>
        <Insights
          list={
            effort
              ? insights({
                  today: effort,
                  before: before.value,
                  scope,
                  // Leads waiting now say nothing about a past day.
                  waiting: picked ? null : waiting.value,
                  newKey,
                  now,
                  past: picked !== null,
                })
              : today.failed
                ? []
                : null
          }
        />
      </section>

      <section aria-labelledby="figures-title" className={styles.section}>
        <h3 id="figures-title" className={styles.sectionTitle}>
          {`${picked ? dayName(picked) : "Today"}, beside last ${weekday}`}
        </h3>
        {day ? (
          <Figures
            day={day}
            was={was}
            weekday={weekday}
            working={working}
            sellers={effort?.sellers.length ?? 0}
            noCalls={
              scope === "inbound" && !day.calls
                ? noCallsNote("inbound", effort, false)
                : null
            }
          />
        ) : today.failed ? (
          <p className={styles.quiet} role="alert">
            Today&apos;s numbers didn&apos;t load. Pull down to try again.
          </p>
        ) : (
          <ul className={styles.kpis} aria-busy="true">
            {[0, 1, 2].map((index) => (
              <li key={index} className={styles.wait} aria-hidden="true" />
            ))}
          </ul>
        )}
        {waiting.value && !picked ? (
          <Link
            className={styles.waiting}
            href={leadsHref("inbound", {
              view: "to_call",
              ...(newKey ? { step: newKey } : {}),
            })}
            data-sx-feature="team_waiting_open"
          >
            <UserPlus size={18} aria-hidden="true" />
            {`${plural(waiting.value, "new lead", "new leads")} waiting for a first call`}
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        ) : null}
        {day && day.notCalledBack ? (
          <Link
            className={styles.waiting}
            href={leadsHref("inbound", { view: "to_call" })}
            data-sx-feature="team_missed_open"
          >
            <PhoneMissed size={18} aria-hidden="true" />
            {`${plural(day.notCalledBack, "missed call", "missed calls")} not called back`}
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        ) : null}
      </section>

      <section aria-labelledby="sellers-title" className={styles.section}>
        <h3 id="sellers-title" className={styles.sectionTitle}>
          Sellers
        </h3>
        {effort ? (
          <Sellers
            effort={effort}
            scope={scope}
            now={now}
            title={picked ? dayName(picked) : "today"}
          />
        ) : (
          <span className={styles.waitBlock} aria-hidden="true" />
        )}
        <p className={styles.footnote}>
          <Timer size={14} aria-hidden="true" />
          Speed to lead counts new Inbound leads: the median minutes from
          arriving to the first call. &quot;Now&quot; is from each seller&apos;s
          last call.
        </p>
      </section>

      <section aria-labelledby="coming-title" className={styles.coming}>
        <h3 id="coming-title" className={styles.sectionTitle}>
          Coming soon
        </h3>
        <ul>
          {COMING.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      {more ? more(effort?.sellers.length ?? 0) : null}
    </div>
  );
}

/** Team today before anything is read (home-outline.tsx). */
export function TeamTodayOutline({ more }: { more?: ReactNode }) {
  return (
    <div className={styles.page} data-team-today="">
      <header className={styles.header}>
        <div className={styles.title}>
          <h2>Team today</h2>
          <p>&nbsp;</p>
        </div>
      </header>
      <ul className={styles.insights} aria-busy="true">
        {[0, 1].map((index) => (
          <li key={index} className={styles.wait} aria-hidden="true" />
        ))}
      </ul>
      <ul className={styles.kpis} aria-busy="true">
        {[0, 1, 2].map((index) => (
          <li key={index} className={styles.wait} aria-hidden="true" />
        ))}
      </ul>
      <span className={styles.waitBlock} aria-hidden="true" />
      {more}
    </div>
  );
}
