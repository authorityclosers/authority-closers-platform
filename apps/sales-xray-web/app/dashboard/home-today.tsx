"use client";

/**
 * Home's calm layout (owner, 28 Oct 2026 meeting, "Home: today's work on top,
 * recent work below"; bugs #70–#72 from his Android phone: empty space, "so
 * much text", "graphs and design are very terrible"):
 * - one header line: Today and its few controls, no row of its own;
 * - the top four, each red until its rule is met, each one tap into Leads;
 * - the second figures in a sideways slider (outcome-tiles, layout "slider");
 * - one recent block: Recent calls, with Activity beside it;
 * - My work: what you did today or this week, against nothing but itself.
 * Only real numbers; a figure the server doesn't send is not drawn.
 * A seller's Home also counts today's work down at the top and ends with
 * their longest breaks (Leads redesign, section 6, 30 Oct 2026).
 */

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import type { HomeBreak, HomeDesk } from "./my-day-client";
import type { Performance } from "../leads/leads-client";
import { Segmented } from "../ui/kit";
import styles from "./home-today.module.css";

/** One of the top four: a number, its red rule, and where it opens. */
export type Four = {
  key: string;
  label: string;
  /** What shows big: a count or a share; null while it loads. */
  value: string | null;
  /** Red until the rule is met (Dipak's table, 28 Oct 2026). */
  red: boolean;
  /** The rule in three or four words, under the number. */
  rule: string;
  href: string;
};

const share = (part: number, whole: number) =>
  whole > 0 ? Math.round((part / whole) * 100) : null;

/**
 * The team's four (owners, admins and managers): New leads nobody has called,
 * Open leads (called, never reached) as a share of all leads, follow-ups past
 * their time, and new leads with no owner.
 */
export function teamFour(
  performance: Performance | null,
  allLeads: number | null,
  unassigned: number | null,
): Four[] {
  const pipeline = performance?.pipeline ?? null;
  const fresh = pipeline ? (pipeline.new ?? 0) : null;
  const open = pipeline ? (pipeline.not_connected ?? 0) : null;
  const openShare =
    open !== null && allLeads !== null ? share(open, allLeads) : null;
  const late = performance
    ? performance.sellers.reduce((sum, seller) => sum + seller.late, 0)
    : null;
  return [
    {
      key: "new",
      label: "New leads",
      value: fresh === null ? null : String(fresh),
      red: (fresh ?? 0) > 0,
      rule: "Red until 0",
      href: "/leads?tab=all&stage=new",
    },
    {
      key: "open",
      label: "Open leads",
      value:
        openShare !== null
          ? `${openShare}%`
          : open === null
            ? null
            : String(open),
      red: openShare !== null ? openShare > 20 : false,
      rule: openShare !== null ? `${open} · red above 20%` : "Red above 20%",
      href: "/leads?tab=all&stage=not_connected",
    },
    {
      key: "follow_ups",
      label: "Follow-ups late",
      value: late === null ? null : String(late),
      red: (late ?? 0) > 0,
      rule: "Red until done",
      href: "/leads?tab=all&due=late",
    },
    {
      key: "no_owner",
      label: "No owner",
      value: unassigned === null ? null : String(unassigned),
      red: (unassigned ?? 0) > 0,
      rule: "Red until 0",
      href: "/leads?tab=all&stage=open&who=unassigned",
    },
  ];
}

/**
 * Your own four (anyone who works leads): New leads you haven't called, Open
 * leads (called, never reached), today's follow-ups, and today's tasks.
 */
export function mineFour(
  desk: HomeDesk | null,
  tasks: { today: number; late: number } | "off" | null,
): Four[] {
  const counts = desk?.counts;
  const openShare = counts ? share(counts.not_connected, counts.open) : null;
  const followUps = counts ? counts.follow_up_due + counts.later_today : null;
  return [
    {
      key: "new",
      label: "New leads",
      value: counts ? String(counts.new) : null,
      red: (counts?.new ?? 0) > 0,
      rule: "Red until 0",
      href: "/leads?tab=all&stage=new",
    },
    {
      key: "open",
      label: "Open leads",
      value: counts ? String(counts.not_connected) : null,
      red: openShare !== null && openShare > 20,
      rule: "Red above 20%",
      href: "/leads?tab=all&stage=not_connected",
    },
    {
      key: "follow_ups",
      label: "Follow-ups today",
      value: followUps === null ? null : String(followUps),
      red: (counts?.follow_up_due ?? 0) > 0,
      rule: "Red until done",
      href: "/leads?tab=all&due=today",
    },
    tasks === "off"
      ? {
          key: "tasks",
          label: "Tasks today",
          value: "–",
          red: false,
          rule: "Open Tasks",
          href: "/leads?tab=tasks",
        }
      : {
          key: "tasks",
          label: "Tasks today",
          value: tasks ? String(tasks.today + tasks.late) : null,
          red: (tasks?.late ?? 0) > 0,
          rule: tasks?.late ? `${tasks.late} past their time` : "Red when late",
          href: "/leads?tab=tasks",
        },
  ];
}

/** Today's title and its few controls on one line (#70: a row of its own left empty space). */
export function TodayBar({
  title = "Today",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className={styles.bar}>
      <h2>{title}</h2>
      {children ? <div className={styles.barEnd}>{children}</div> : null}
    </div>
  );
}

/** The top four: 2 x 2 on a phone, one row on a computer. */
export function FourTiles({ tiles, label }: { tiles: Four[]; label: string }) {
  return (
    <ul className={styles.four} aria-label={label}>
      {tiles.map((tile) => (
        <li key={tile.key}>
          <Link
            className={styles.tile}
            href={tile.href}
            data-four={tile.key}
            data-red={tile.red || undefined}
            aria-busy={tile.value === null || undefined}
            aria-description={tile.rule}
          >
            {/* No rule line on the card (owner, 31 Oct 2026): red is the
                number's colour and a small dot. */}
            <span className={styles.label}>{tile.label}</span>
            <strong className={styles.value}>{tile.value ?? " "}</strong>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** One recent block: Recent calls, or the Activity beside them, and See all. */
export function RecentToggle({
  calls,
  activity,
  seeAll,
}: {
  calls: ReactNode;
  activity: ReactNode;
  /** Where each tab's full list lives, if it has a page of its own. */
  seeAll: { calls?: string; activity?: string };
}) {
  const [shown, setShown] = useState<"calls" | "activity">("calls");
  const link = seeAll[shown];
  return (
    <section className={styles.recent} aria-label="Recent">
      <div className={styles.recentHead}>
        <Segmented
          label="Recent"
          value={shown}
          onChange={setShown}
          items={[
            { key: "calls", label: "Recent calls" },
            { key: "activity", label: "Activity" },
          ]}
        />
        {link ? (
          <Link className={styles.more} href={link}>
            See all
            <ChevronRight size={15} aria-hidden="true" />
          </Link>
        ) : null}
      </div>
      <div className={styles.recentBody}>
        {shown === "calls" ? calls : activity}
      </div>
    </section>
  );
}

const talk = (seconds: number) => {
  const minutes = Math.round(seconds / 60);
  return minutes < 60
    ? `${minutes}m`
    : `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
};

/**
 * Analyse yourself (28 Oct 2026 meeting): you against yourself, for today,
 * this week or this month: calls attempted, connected, not connected, talk
 * time and follow-ups done, from the calls Recent calls lists.
 */
export function MyWork({ desk }: { desk: HomeDesk | null }) {
  const [when, setWhen] = useState<"today" | "week" | "month">("today");
  const numbers =
    when === "today"
      ? (desk?.numbers ?? null)
      : when === "week"
        ? (desk?.numbers_week ?? null)
        : (desk?.numbers_month ?? null);
  const figures = numbers
    ? [
        { label: "Attempted", value: String(numbers.calls) },
        { label: "Connected", value: String(numbers.connected) },
        // Attempted minus connected (the server's not_connected).
        {
          label: "Not connected",
          value: String(Math.max(0, numbers.calls - numbers.connected)),
        },
        { label: "Talk time", value: talk(numbers.talk_seconds) },
        { label: "Follow-ups done", value: String(numbers.follow_ups_done) },
      ]
    : null;
  return (
    <section className={styles.work} aria-labelledby="my-work-title">
      <div className={styles.workHead}>
        <h2 id="my-work-title">Analyse yourself</h2>
        {desk?.numbers_week ? (
          <Segmented
            label="Analyse yourself for"
            value={when}
            onChange={setWhen}
            items={[
              { key: "today", label: "Today" },
              { key: "week", label: "Week" },
              ...(desk.numbers_month
                ? [{ key: "month" as const, label: "Month" }]
                : []),
            ]}
          />
        ) : null}
      </div>
      <dl className={styles.figures}>
        {(figures ?? Array.from({ length: 5 }, () => null)).map(
          (figure, index) => (
            <div key={figure?.label ?? index} aria-busy={!figure || undefined}>
              <dt>{figure?.label ?? " "}</dt>
              <dd>{figure?.value ?? " "}</dd>
            </div>
          ),
        )}
      </dl>
      {/* One Performance button on Home (Leads redesign, section 6). */}
      <Link className={styles.workMore} href="/growth">
        Performance
        <ChevronRight size={16} aria-hidden="true" />
      </Link>
    </section>
  );
}

/**
 * Today's work counting down (Leads redesign, section 6: "20 → 19 → 18"):
 * the leads still to call today out of today's whole list, falling as calls
 * happen.
 */
export function TodayCountdown({ desk }: { desk: HomeDesk | null }) {
  const today = desk?.to_call_today;
  const total = today ? today.left + today.called : 0;
  if (!today || total === 0) return null;
  return (
    <section className={styles.countdown} aria-labelledby="countdown-title">
      <div className={styles.countdownHead}>
        <h2 id="countdown-title">To call today</h2>
        <span>{`${today.called} called`}</span>
      </div>
      <p className={styles.countdownFigure}>
        <strong>{today.left}</strong>
        <span>{`of ${total} left`}</span>
      </p>
      <div
        className={styles.countdownBar}
        role="progressbar"
        aria-label="Called today"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={today.called}
      >
        <span
          style={{ width: `${Math.round((today.called / total) * 100)}%` }}
        />
      </div>
    </section>
  );
}

const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

/** "45 min", "1 h", "1 h 20 min". */
export function breakLength(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} h${rest ? ` ${rest} min` : ""}`;
}

/** One break as a row: when, how long, red unless the team set it. */
export function BreakRow({ gap }: { gap: HomeBreak }) {
  return (
    <li className={styles.breakRow} data-red={gap.planned ? undefined : ""}>
      <span>
        {`${CLOCK.format(new Date(gap.start))} – ${CLOCK.format(new Date(gap.end))}`}
        {gap.planned ? <small>Set break</small> : null}
      </span>
      <strong>{`${gap.approximate ? "≈ " : ""}${breakLength(gap.minutes)}`}</strong>
    </li>
  );
}

/**
 * Your 3 longest breaks today, at the very end of Home (Leads redesign,
 * section 6): the gaps between your calls inside the working day (the team's
 * work hours when set, else your first call to your last), longest first. A
 * gap that isn't a set break is red. ≈ marks a gap next to a call from the
 * app's Call button, whose time is when you came back to the app.
 */
export function YourBreaks({ desk }: { desk: HomeDesk | null }) {
  const breaks = desk?.breaks;
  if (!Array.isArray(breaks)) return null;
  return (
    <section className={styles.breaks} aria-labelledby="breaks-title">
      <h2 id="breaks-title">Your 3 longest breaks today</h2>
      {breaks.length ? (
        <ol className={styles.breakList}>
          {breaks.map((gap) => (
            <BreakRow key={gap.start} gap={gap} />
          ))}
        </ol>
      ) : (
        <p className={styles.breakNote}>No breaks between calls yet today.</p>
      )}
      {breaks.some((gap) => gap.approximate) ? (
        <p className={styles.breakNote}>
          ≈ Next to a call from the app&apos;s Call button: its time is when you
          came back to the app.
        </p>
      ) : null}
    </section>
  );
}
