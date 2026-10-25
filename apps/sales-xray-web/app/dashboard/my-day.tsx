"use client";

/**
 * My day on Home (owner program, 25 Oct 2026, on Lead OS's team engine): who
 * to call now with why, today's numbers against targets, and, when today is
 * empty, the next useful thing (what is next, this week beside last week, the
 * team's open leads) instead of a page of zeros.
 */

import { ChevronRight, UsersRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { handOverLead } from "../leads/lead-handoff";
import { when } from "../leads/leads-client";
import { Avatar, Delta } from "../ui/kit";
import {
  becauseLine,
  fromDesk,
  METRIC_WORDS,
  readMyDay,
  type HomeDesk,
  type Metric,
  type MetricProgress,
  type MyDay,
  type MyDayItem,
} from "./my-day-client";
import home from "./sales-home.module.css";
import styles from "./my-day.module.css";

export type MyDayState =
  | { status: "loading" }
  | { status: "ready"; value: MyDay }
  | { status: "error" };

export function useMyDay(): MyDayState {
  const [state, setState] = useState<MyDayState>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    readMyDay(controller.signal)
      .then((value) => setState({ status: "ready", value }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });
    return () => controller.abort();
  }, []);
  return state;
}

const ORDER: Metric[] = ["calls", "connects", "follow_ups", "meetings"];

const isLate = (item: MyDayItem, now: number) =>
  item.due_at ? Date.parse(item.due_at) < now - 60_000 : false;

/** One thing to do now: the name and why, a Late mark when it is past due. */
export function DoNowRow({ item, now }: { item: MyDayItem; now: number }) {
  const late = isLate(item, now);
  return (
    <li>
      <Link
        className={home.row}
        href="/leads"
        onClick={() => handOverLead(item.lead_id)}
        data-late={late ? "" : undefined}
      >
        <Avatar name={item.lead_name} size={34} />
        <span className={home.rowMain}>
          <strong>{displayName(item.lead_name)}</strong>
          <small>{becauseLine(item.because) || "Due now"}</small>
        </span>
        {late ? <span className={home.late}>Late</span> : null}
        <ChevronRight size={16} aria-hidden="true" />
      </Link>
    </li>
  );
}

/** What is next when nothing is due: the next few calls and tasks, with when. */
export function NextUp({
  items,
}: {
  items: NonNullable<MyDay["fallback"]>["next_up"];
}) {
  if (!items.length) return null;
  return (
    <ol className={home.list} aria-label="Next up">
      {items.map((item) => (
        <li key={`${item.lead_id}-${item.at}`}>
          <Link
            className={home.row}
            href="/leads"
            onClick={() => handOverLead(item.lead_id)}
          >
            <Avatar name={item.lead_name} size={34} />
            <span className={home.rowMain}>
              <strong>{displayName(item.lead_name)}</strong>
              <small>{`${item.what} ${when(item.at)}`}</small>
            </span>
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ol>
  );
}

/** No leads of mine yet: what the team has, and how new ones reach me. */
export function TeamPoolCard({
  desk,
  onShare,
}: {
  desk: HomeDesk;
  /** Owners and managers: open Share out leads here. */
  onShare?: () => void;
}) {
  const pool = desk.team_pool;
  if (!pool?.open) return null;
  const leads = pool.open === 1 ? "1 open lead" : `${pool.open} open leads`;
  const unowned = pool.unassigned
    ? `, ${pool.unassigned} with no owner yet`
    : "";
  return (
    <div className={styles.pool}>
      <span className={styles.poolIcon} aria-hidden="true">
        <UsersRound size={20} />
      </span>
      <div className={styles.poolText}>
        <strong>No leads are yours yet</strong>
        <span>{`Your team has ${leads}${unowned}.`}</span>
        <span>
          {pool.may_take
            ? "New leads come to you the moment they arrive."
            : "You aren't taking new leads. Turn it on above to get the next ones."}
        </span>
      </div>
      {desk.me.can_manage && onShare ? (
        <button type="button" className={styles.share} onClick={onShare}>
          Share out leads
        </button>
      ) : (
        <Link
          className={home.more}
          href={
            desk.me.can_manage
              ? "/leads?tab=all&stage=open&who=unassigned"
              : "/leads"
          }
        >
          {desk.me.can_manage ? "Share out leads" : "Open Leads"}
        </Link>
      )}
    </div>
  );
}

function Target({ line }: { line: MetricProgress }) {
  const met = line.done >= line.target;
  const share = Math.min(1, line.target ? line.done / line.target : 0);
  const tone = met ? "good" : line.behind ? "warn" : "on";
  return (
    <li className={styles.target} data-tone={tone}>
      <span className={styles.targetHead}>
        <span>
          {METRIC_WORDS[line.metric]}
          {line.period === "week" ? " this week" : ""}
        </span>
        <strong>{`${line.done} of ${line.target}`}</strong>
      </span>
      <span
        className={styles.track}
        role="meter"
        aria-label={`${METRIC_WORDS[line.metric]}: ${line.done} of ${line.target}`}
        aria-valuemin={0}
        aria-valuemax={line.target}
        aria-valuenow={Math.min(line.done, line.target)}
      >
        <span
          className={styles.bar}
          style={{ width: `${Math.round(share * 100)}%` }}
        />
      </span>
      <small>
        {met
          ? "Done for today"
          : line.behind
            ? `${line.short} behind pace`
            : "On pace"}
      </small>
    </li>
  );
}

function Figures({
  label,
  values,
  before,
  beforeWord,
}: {
  label: string;
  values: Partial<Record<Metric, number>>;
  before?: Partial<Record<Metric, number>> | null;
  beforeWord?: string;
}) {
  const shown = ORDER.filter((metric) => values[metric]);
  if (!shown.length) return null;
  return (
    <section className={styles.numbers} aria-label={label}>
      <h3 className={styles.numbersTitle}>{label}</h3>
      <dl
        className={`${home.dayStrip} ${styles.strip}`}
        data-count={shown.length}
      >
        {shown.map((metric) => (
          <div key={metric}>
            <dt>{METRIC_WORDS[metric]}</dt>
            <dd className={styles.figure}>
              {values[metric]}
              {before && beforeWord === undefined ? (
                <Delta
                  value={values[metric] ?? 0}
                  previous={before[metric] ?? 0}
                />
              ) : null}
            </dd>
            {before && beforeWord && before[metric] ? (
              <dd className={styles.before}>
                {`${beforeWord} ${before[metric]}`}
              </dd>
            ) : null}
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * The seller's numbers: targets with progress when there are targets; today's
 * numbers (beside yesterday's) when there are any; else this week beside last
 * week; else nothing (a new account has the start card above instead).
 */
export function DayNumbers({
  desk,
  myDay,
}: {
  desk: HomeDesk;
  myDay: MyDayState;
}) {
  const day = myDay.status === "ready" ? myDay.value : null;
  if (day?.progress.length)
    return (
      <section className={styles.numbers} aria-label="Your targets">
        <h3 className={styles.numbersTitle}>Your targets</h3>
        <ul className={styles.targets}>
          {[...day.progress]
            .sort((a, b) =>
              a.period === b.period
                ? ORDER.indexOf(a.metric) - ORDER.indexOf(b.metric)
                : a.period === "day"
                  ? -1
                  : 1,
            )
            .map((line) => (
              <Target key={`${line.metric}-${line.period}`} line={line} />
            ))}
        </ul>
      </section>
    );
  const today = day ? day.today : fromDesk(desk.numbers);
  const yesterday = desk.numbers_yesterday
    ? fromDesk(desk.numbers_yesterday)
    : null;
  if (ORDER.some((metric) => today[metric]))
    return (
      <Figures
        label="Today"
        values={today}
        before={yesterday}
        beforeWord="Yesterday"
      />
    );
  if (day?.fallback)
    return (
      <Figures
        label="This week"
        values={day.fallback.week}
        before={day.fallback.last_week}
      />
    );
  if (yesterday && ORDER.some((metric) => yesterday[metric]))
    return <Figures label="Yesterday" values={yesterday} />;
  const week = desk.numbers_week ? fromDesk(desk.numbers_week) : null;
  return week ? <Figures label="Last 7 days" values={week} /> : null;
}
