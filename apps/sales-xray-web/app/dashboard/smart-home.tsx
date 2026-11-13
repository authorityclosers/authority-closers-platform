/**
 * Home's smart pieces (owner's pick, 10 Nov 2026: Home "Me" as H5 Smart lists,
 * with H1's red late time, H3's task-due boxes, H4's typed rows with lines and
 * H2's rings; H2's day column kept apart for later). Each piece draws only
 * what it is given, so Home, the outline and any later screen share them.
 *  - SmartCounter: a coloured icon, the number on the right, a label and a
 *    caption; it opens the exact list it counts.
 *  - TaskMarks: one small box per task due today, ticked when done (H3).
 *  - TodayList and TodayRow: the day's tasks and follow-ups in time order,
 *    each with its time (red when late, with the word Late), its kind and
 *    lines between rows (H1, H4, H5).
 *  - DoneToday and DoneRing: today's numbers, each beside a ring whose arc is
 *    a real share or nothing (H2's rings; honest numbers, 3 Nov 2026).
 *  - DayTimeline: H2's hour column, built and tested, not on Home yet ("maybe
 *    later on we can add it").
 */

import { Check, ChevronRight, Phone } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./smart-home.module.css";

export type CounterTone = "teal" | "amber" | "indigo" | "slate";

/** One of Today's overview tiles (H5). The words come first for a screen
 *  reader; the number sits top right beside the icon. */
export function SmartCounter({
  id,
  icon,
  tone,
  label,
  note,
  value,
  unknown = false,
  href,
  marks,
}: {
  /** Names the tile for its tests and its probes: data-card. */
  id: string;
  icon: ReactNode;
  tone: CounterTone;
  label: string;
  note: ReactNode;
  /** The number (or a counter drawing it); undefined or null while it is
   *  read, and a quiet bar holds its place. */
  value: ReactNode;
  /** Not loaded: a dash, never a 0 it doesn't know, and no link. */
  unknown?: boolean;
  href: string;
  /** Under the caption, e.g. TaskMarks. */
  marks?: ReactNode;
}) {
  // A tile that opens its list says so with a chevron after its number (the
  // 13 Nov 2026 meeting: what is tappable must look tappable; seller Flow 1,
  // F4), where a name that wraps at 130 % text can't leave it on a line of
  // its own. One that didn't load opens nothing, and has none.
  const body = (
    <>
      <span className={styles.icon} data-icon="" aria-hidden="true">
        {icon}
      </span>
      <span className={styles.label}>{label}</span>
      <strong
        className={styles.value}
        aria-busy={(!unknown && value == null) || undefined}
        data-unknown={unknown || undefined}
      >
        {unknown ? "–" : value == null ? " " : value}
        {unknown || value == null ? null : <Go />}
      </strong>
      <span className={styles.note}>{note}</span>
      {marks ? <span className={styles.marks}>{marks}</span> : null}
    </>
  );
  return unknown ? (
    <div className={styles.counter} data-card={id} data-tone={tone}>
      {body}
    </div>
  ) : (
    <Link
      className={styles.counter}
      href={href}
      data-card={id}
      data-tone={tone}
    >
      {body}
    </Link>
  );
}

/** The chevron after a tappable tile's number: it opens something. */
function Go() {
  return <ChevronRight className={styles.go} aria-hidden="true" data-go="" />;
}

/** One box per task due today, the done ones ticked (H3's "task due"). At
 *  most `max` boxes, then "+N". Drawn only: the tile's words say the count. */
export function TaskMarks({
  done,
  open,
  max = 5,
}: {
  done: number;
  open: number;
  max?: number;
}) {
  const all = done + open;
  if (!all) return null;
  const shown = Math.min(all, max);
  return (
    <span className={styles.taskMarks} aria-hidden="true">
      {Array.from({ length: shown }, (_, index) => (
        <i key={index} data-done={index < done || undefined}>
          {index < done ? (
            <svg viewBox="0 0 12 12" width="10" height="10">
              <path d="M2.5 6.2 5 8.6l4.5-5" />
            </svg>
          ) : null}
        </i>
      ))}
      {all > shown ? <span>+{all - shown}</span> : null}
    </span>
  );
}

/** A time as the picture writes it: "11:30 am", in India time. */
const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
export const clockTime = (at: string | null) =>
  at
    ? CLOCK.format(new Date(at)).replace(
        /\s?(AM|PM)$/,
        (_, half: string) => ` ${half.toLowerCase()}`,
      )
    : "";

const IST_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });
const SHORT_DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});

/** A row's time: the clock today, the day before that ("9 Nov"), so a task
 *  late since an earlier day never reads as one at that time today. */
export const listTime = (at: string | null, now: Date = new Date()) => {
  if (!at) return "Today";
  const date = new Date(at);
  return IST_DAY.format(date) === IST_DAY.format(now)
    ? clockTime(at)
    : SHORT_DAY.format(date);
};

export type TodayKind = "task" | "follow_up";
const KIND_WORDS: Record<TodayKind, string> = {
  task: "Task",
  follow_up: "Follow-up",
};

/** A Today's list block (H5): its title and link inside the card, the rows
 *  under it with a line between each, or one line saying why there are none. */
export function TodayList({
  id,
  title,
  end,
  rows,
  empty,
  after,
}: {
  id: string;
  title: string;
  /** Beside the title: See all. */
  end?: ReactNode;
  /** List items (SwipeRow, or li), each holding a TodayRow. */
  rows: ReactNode[];
  /** Instead of the rows when there are none: All clear, Loading. */
  empty: ReactNode;
  /** Under the rows: a quiet line, a sheet. */
  after?: ReactNode;
}) {
  return (
    <section className={styles.card} aria-labelledby={id}>
      <div className={styles.cardHead}>
        <h2 id={id}>{title}</h2>
        {end}
      </div>
      {rows.length ? <ul className={styles.rows}>{rows}</ul> : empty}
      {after}
    </section>
  );
}

/** A task's box in a row: one tap marks it done, a second undoes it. */
export function TickMark({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className={styles.tick}>
      <input
        type="checkbox"
        aria-label={label}
        checked={checked}
        onChange={onChange}
      />
      <span aria-hidden="true">
        <Check size={14} strokeWidth={3} />
      </span>
    </label>
  );
}

/** A follow-up's call in a row. */
export function CallMark({
  href,
  label,
  onClick,
}: {
  href: string;
  label: string;
  onClick?: () => void;
}) {
  return (
    <Link
      className={styles.call}
      href={href}
      aria-label={label}
      onClick={onClick}
    >
      <Phone size={18} aria-hidden="true" />
    </Link>
  );
}

/** One row: the tap target on the left (a box or a call), the time in its own
 *  column (red when late, H1), then the words, and under them the kind and
 *  Late, so colour never carries it alone (H1, H4). */
export function TodayRow({
  mark,
  kind,
  at,
  late = false,
  done = false,
  title,
  extra,
  now,
}: {
  mark: ReactNode;
  kind: TodayKind;
  at: string | null;
  late?: boolean;
  done?: boolean;
  title: ReactNode;
  /** After the chips: the lead's name, a note. */
  extra?: ReactNode;
  /** Today, for the time's day; the clock's own by default. */
  now?: Date;
}) {
  return (
    <div
      className={styles.row}
      data-today-row=""
      data-kind={kind}
      data-late={late || undefined}
      data-done={done || undefined}
    >
      <span className={styles.mark} data-col="mark">
        {mark}
      </span>
      <span
        className={styles.time}
        data-col="time"
        data-late-time={late || undefined}
      >
        {listTime(at, now)}
      </span>
      <span className={styles.words} data-col="title">
        <span className={styles.title}>{title}</span>
        <span className={styles.chips}>
          <span className={styles.kind} data-kind={kind}>
            {KIND_WORDS[kind]}
          </span>
          {late ? <span className={styles.late}>Late</span> : null}
          {extra ? <span className={styles.extra}>{extra}</span> : null}
        </span>
      </span>
    </div>
  );
}

/** A ring and the icon in it (H2). The arc shows a real share, 0 to 1; with
 *  none, only the track is drawn, never a made-up amount. */
export function DoneRing({
  icon,
  share = null,
}: {
  icon: ReactNode;
  share?: number | null;
}) {
  const r = 17;
  const round = 2 * Math.PI * r;
  const part = share == null ? null : Math.max(0, Math.min(1, share));
  return (
    <span
      className={styles.ring}
      aria-hidden="true"
      data-share={part ?? undefined}
    >
      <svg viewBox="0 0 40 40" width="40" height="40">
        <circle className={styles.track} cx="20" cy="20" r={r} />
        {part ? (
          <circle
            className={styles.arc}
            cx="20"
            cy="20"
            r={r}
            strokeDasharray={`${(part * round).toFixed(2)} ${round.toFixed(2)}`}
          />
        ) : null}
      </svg>
      <span className={styles.ringIcon}>{icon}</span>
    </span>
  );
}

export type DoneFigure = {
  key: string;
  label: string;
  value: ReactNode;
  href: string;
  icon: ReactNode;
  share?: number | null;
};

/** Done today (H5): two by two on a phone, one row where there is room; each
 *  number opens what it counts. */
export function DoneToday({
  id,
  title = "Done today",
  end,
  note,
  figures,
  children,
}: {
  id: string;
  title?: string;
  end?: ReactNode;
  /** What the numbers count: "Inbound calls only · Today". */
  note?: ReactNode;
  figures: DoneFigure[];
  /** Under the numbers: a quiet line. */
  children?: ReactNode;
}) {
  return (
    <section className={styles.card} aria-labelledby={id}>
      <div className={styles.cardHead}>
        <h2 id={id}>{title}</h2>
        {end}
      </div>
      {note ? <p className={styles.doneNote}>{note}</p> : null}
      <ul className={styles.done}>
        {figures.map((figure) => (
          <li key={figure.key}>
            <Link href={figure.href} data-done={figure.key}>
              <span className={styles.doneLabel}>
                <Words text={figure.label} />
              </span>
              <DoneRing icon={figure.icon} share={figure.share} />
              <strong className={styles.doneValue}>
                {figure.value ?? " "}
              </strong>
            </Link>
          </li>
        ))}
      </ul>
      {children}
    </section>
  );
}

/** Words that wrap between them, never at a hyphen ("Follow-" over "ups
 *  done" at 130 % text). */
function Words({ text }: { text: string }) {
  const words = text.split(" ");
  return (
    <>
      {words.map((word, index) => (
        <span key={index} className={styles.word}>
          {index ? ` ${word}` : word}
        </span>
      ))}
    </>
  );
}

export type DayItem = {
  key: string;
  at: string;
  title: string;
  kind: TodayKind;
  late?: boolean;
  done?: boolean;
};

const HOUR = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  hourCycle: "h23",
  timeZone: "Asia/Kolkata",
});
const MINUTE = new Intl.DateTimeFormat("en-US", {
  minute: "numeric",
  timeZone: "Asia/Kolkata",
});
const hourOf = (at: Date) => Number(HOUR.format(at)) % 24;
const minuteOf = (at: Date) => Number(MINUTE.format(at));
const hourWords = (hour: number) =>
  `${hour % 12 || 12} ${hour < 12 ? "am" : "pm"}`;

/** H2's "Your day": the working hours down a rail, each task or follow-up at
 *  its hour, and a Now line. Standalone, not on Home yet (owner, 10 Nov 2026:
 *  "maybe later on we can add it"). */
export function DayTimeline({
  id = "day-title",
  title = "Your day",
  items,
  now = new Date(),
  from = 9,
  to = 19,
}: {
  id?: string;
  title?: string;
  items: DayItem[];
  now?: Date;
  /** The first and last hours drawn, in India time; items outside widen it. */
  from?: number;
  to?: number;
}) {
  const hours = items.map((item) => hourOf(new Date(item.at)));
  const first = Math.min(from, ...hours);
  const last = Math.max(to, ...hours);
  const nowHour = hourOf(now);
  const nowMinute = minuteOf(now);
  const rows: ReactNode[] = [];
  for (let hour = first; hour <= last; hour += 1) {
    const here = items
      .filter((item) => hourOf(new Date(item.at)) === hour)
      .sort((a, b) => a.at.localeCompare(b.at));
    rows.push(
      <li key={`h${hour}`} className={styles.dayHour}>
        <span className={styles.dayTime}>{hourWords(hour)}</span>
        <span className={styles.dayDot} aria-hidden="true" />
      </li>,
    );
    if (hour === nowHour && nowMinute < 30)
      rows.push(<NowLine key="now" now={now} />);
    for (const item of here)
      rows.push(
        <li
          key={item.key}
          className={styles.dayItem}
          data-late={item.late || undefined}
          data-done={item.done || undefined}
        >
          <span className={styles.dayTime}>{clockTime(item.at)}</span>
          <span className={styles.dayState} aria-hidden="true" />
          <span className={styles.dayWords}>
            {item.title}
            <span>
              {` · ${KIND_WORDS[item.kind]}`}
              {item.late ? <b> · Late</b> : null}
            </span>
          </span>
        </li>,
      );
    if (hour === nowHour && nowMinute >= 30)
      rows.push(<NowLine key="now" now={now} />);
  }
  return (
    <section className={styles.card} aria-labelledby={id}>
      <div className={styles.cardHead}>
        <h2 id={id}>{title}</h2>
      </div>
      <ol className={styles.day}>{rows}</ol>
    </section>
  );
}

function NowLine({ now }: { now: Date }) {
  return (
    <li className={styles.dayNow} data-now="">
      <span className={styles.dayTime}>{clockTime(now.toISOString())}</span>
      <span className={styles.dayNowRule} aria-hidden="true" />
      <span className={styles.dayNowWord}>Now</span>
    </li>
  );
}
