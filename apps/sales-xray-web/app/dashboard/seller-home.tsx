"use client";

/**
 * A seller's Home, as Dipak's picture (owner order, 2 Nov 2026,
 * docs/handoffs/dipak-home-20261102): the work to do. Each block below stands
 * alone, in the picture's order:
 *  1. Inbound Leads | Cold Leads, only for someone with both, with one short
 *     line under it; on Cold, one row when fresh inbound leads wait.
 *  2. Today: New leads (Inbound) or Unworked leads (Cold), Open leads,
 *     Follow-ups today (the side's own) and Tasks today (shared, never a
 *     call), each with one caption. Each card opens the exact Leads list it
 *     counts.
 *  3. Next to call: one customer, and Call now or Start Cold Calling.
 *  4. Today's tasks: three at most, + Add, See all.
 *  5. Upcoming follow-ups: two at most, each with its call button, See all.
 *  6. Recent calls: the last three, each with its outcome and time, never the
 *     capture line (Calls has it, with its fix).
 *  7. Today's performance: two by two (Attempted, Connected, Talk time,
 *     Follow-ups done), each opening the calls or follow-ups it counts.
 * The desk carries both sides, so the selector switches with no second read.
 */

import { Check, ChevronRight, Phone, PhoneCall } from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { displayName } from "../display-name";
import { AddTaskSheet } from "../leads/add-task-sheet";
import {
  CallRows,
  outcomeLine,
  rowFromActivity,
  useGo,
  useWeekActivity,
  weekCalls,
} from "../calls/call-rows";
import { CallRowsSkeleton } from "../calls/phone-calls";
import { FinishRow } from "../leads/finish-row";
import {
  handOverAnswer,
  handOverLead,
  handOverRound,
} from "../leads/lead-handoff";
import {
  ago,
  deskRequest,
  nextCallTime,
  readTasks,
  setFollowUp,
  snoozeTask,
  taskAction,
  type TaskSnoozeChoice,
  type ListedTask,
} from "../leads/leads-client";
import { callLogStatus, inPhoneApp } from "../leads/native-phone";
import { notify } from "../notice-center";
import { SideSelector, type Side } from "../ui/side-selector";
import { retryHome } from "./home-load";
import { LaterSheet, SwipeRow, type Later } from "./home-swipe";
import { breakLength } from "./home-today";
import { Count } from "./metric-pager";
import type { HomeDesk, HomeSide } from "./my-day-client";
import styles from "./seller-home.module.css";
import { talkOrDash } from "./talk-time";

/** Which lead types this seller works: GET /sides (Leads session, 31 Oct). */
type SidesAccess = { inbound: boolean; cold: boolean };

/** Both types, until an owner access setting exists (handoff: owner decides). */
export function useSidesAccess(enabled = true): SidesAccess | null {
  const [access, setAccess] = useState<SidesAccess | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    deskRequest<{
      inbound?: { leads?: number };
      cold?: { imported?: number };
    }>("/sides?scope=mine", { signal: controller.signal }).then(
      (sides) =>
        setAccess({
          inbound: (sides?.inbound?.leads ?? 0) > 0,
          cold: (sides?.cold?.imported ?? 0) > 0,
        }),
      () => {
        // Not known: Inbound alone, the default, with no selector.
        if (!controller.signal.aborted)
          setAccess({ inbound: true, cold: false });
      },
    );
    return () => controller.abort();
  }, [enabled]);
  return access;
}

/** A Leads list address, on the side picked (Leads opens on Inbound, To Call). */
export function leadsHref(side: Side, query: Record<string, string>): string {
  const params = new URLSearchParams(query);
  if (side === "cold") params.set("side", "cold");
  const text = params.toString();
  return text ? `/leads?${text}` : "/leads";
}

const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
const when = (at: string | null) => (at ? CLOCK.format(new Date(at)) : "");

const DAY = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});
const IST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** A time with its day when it isn't today (QA, 31 Oct 2026: "10:00 AM",
 *  but which day?): "Tomorrow, 10:00 AM", "Mon, 3 Nov, 10:00 AM". */
const whenDay = (at: string | null) => {
  if (!at) return "";
  const date = new Date(at);
  const day = IST_DATE.format(date);
  const today = IST_DATE.format(new Date());
  const tomorrow = IST_DATE.format(new Date(Date.now() + 86_400_000));
  const time = CLOCK.format(date);
  if (day === today) return time;
  if (day === tomorrow) return `Tomorrow, ${time}`;
  return `${DAY.format(date)}, ${time}`;
};

/** A task's type tag: its lead's side, or General for a task of your own. */
type TaskTag = Side | "general";
const TAG_WORDS: Record<TaskTag, string> = {
  inbound: "Inbound",
  cold: "Cold",
  general: "General",
};
const tagOf = (task: ListedTask): TaskTag | null =>
  !task.lead_id
    ? "general"
    : ((task as ListedTask & { lead_side?: Side | null }).lead_side ?? null);

/** Today's tasks with done and undo: the box ticks at once and goes back if
 *  the server says no, so the screen never shows work that didn't happen. */
export function useTaskList() {
  const today = useTodayTasks();
  const { tasks, setTasks } = today;
  const done = (task: ListedTask) => {
    const next = task.status === "done" ? "undo" : "done";
    const before = tasks ?? [];
    setTasks(
      before.map((item) =>
        item.task_id === task.task_id
          ? { ...item, status: next === "done" ? "done" : "open" }
          : item,
      ),
    );
    taskAction(task, next).then(
      (saved) =>
        setTasks(
          before.map((item) => (item.task_id === saved.task_id ? saved : item)),
        ),
      () => setTasks(before),
    );
  };
  return {
    tasks,
    overdue: today.overdue,
    failed: today.failed,
    reload: today.reload,
    done,
  };
}

/** The Tasks page's Today, and how many are overdue: one truth with Tasks
 *  (persona QA, 31 Oct 2026: Home and Tasks counted different tasks). */
export function useTodayTasks(): {
  tasks: ListedTask[] | null;
  overdue: number | null;
  failed: boolean;
  setTasks: (next: ListedTask[]) => void;
  reload: () => void;
} {
  const [tasks, setTasks] = useState<ListedTask[] | null>(null);
  const [overdue, setOverdue] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    readTasks("today", controller.signal).then(
      (list) => {
        setTasks(list.tasks);
        setOverdue(list.counts.overdue ?? 0);
      },
      () => {
        if (!controller.signal.aborted) setFailed(true);
      },
    );
    return () => controller.abort();
  }, [attempt]);
  const reload = useCallback(() => {
    setFailed(false);
    setAttempt((value) => value + 1);
  }, []);
  return { tasks, overdue, failed, setTasks, reload };
}

function Head({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className={styles.head}>
      <h2 id={id}>{title}</h2>
      {children ? <div className={styles.headEnd}>{children}</div> : null}
    </div>
  );
}

function SeeAll({ href }: { href: string }) {
  return (
    <Link className={styles.seeAll} href={href}>
      See all
      <ChevronRight size={16} aria-hidden="true" />
    </Link>
  );
}

/** 1. The lead type, only for someone with both (handoff items 05-07). */
export function SideBlock({
  side,
  access,
  own,
  inbound,
  onSide,
}: {
  side: Side;
  access: SidesAccess;
  own: HomeSide | null;
  inbound: HomeSide | null;
  onSide: (side: Side) => void;
}) {
  if (!access.inbound || !access.cold) return null;
  const waiting = side === "cold" ? (inbound?.counts.new ?? 0) : 0;
  return (
    <>
      <SideSelector value={side} onChange={onSide} tone="calm" />
      <p className={styles.sideLine}>
        {side === "cold"
          ? "Your assigned cold prospecting database"
          : "Your assigned inbound enquiries"}
      </p>
      {waiting > 0 && own ? (
        <Link
          className={styles.alert}
          href={leadsHref("inbound", { view: "to_call", step: "new" })}
        >
          {`${waiting} fresh inbound ${waiting === 1 ? "lead needs" : "leads need"} attention`}
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      ) : null}
    </>
  );
}

/** 2. Four cards, each opening the exact list it counts (items 08-12). */
export function TodayCards({
  side,
  own,
  tasks,
}: {
  side: Side;
  own: HomeSide | null;
  tasks: number | null;
}) {
  const cold = side === "cold";
  const counts = own?.counts;
  const cards = [
    {
      key: "new",
      label: cold ? "Unworked leads" : "New leads",
      note: cold ? "Never attempted" : "First call pending",
      value: counts?.new,
      href: leadsHref(side, { view: "to_call", step: own?.new_key ?? "new" }),
    },
    {
      key: "open",
      // The Open Leads stage, in words of its own: the open-lead limit counts
      // every open Inbound lead (ph1-33, 1 Nov 2026: 0 here beside 908 there).
      label: "Open leads",
      note: "Needs further discussion",
      value: counts?.open_leads,
      href: leadsHref(side, {
        view: "all",
        step: own?.open_key ?? "open_leads",
      }),
    },
    {
      key: "follow_ups",
      label: "Follow-ups today",
      note: "Scheduled for today",
      value: counts?.follow_ups_today,
      href: leadsHref(side, { view: "follow_ups", when: "today" }),
    },
    {
      key: "tasks",
      label: "Tasks today",
      note: "All work types",
      value: tasks,
      href: "/leads?tab=tasks",
    },
  ];
  return (
    <section className={styles.block} aria-labelledby="today-title">
      <Head id="today-title" title="Today">
        <span className={styles.sideWord}>
          {cold ? "Cold lead activity" : "Inbound lead activity"}
        </span>
      </Head>
      <ul className={styles.cards}>
        {cards
          // A card whose stage the organisation doesn't have is left
          // out, never a raw "open_leads" (phone personas, 31 Oct 2026).
          .filter(
            (card) =>
              !(own && card.key === "new" && own.new_key === null) &&
              !(own && card.key === "open" && own.open_key === null),
          )
          .map((card) => (
            <li key={card.key}>
              <Link
                className={styles.card}
                href={card.href}
                data-card={card.key}
              >
                <span className={styles.cardLabel}>{card.label}</span>
                <strong aria-busy={card.value == null || undefined}>
                  {card.value == null ? (
                    " "
                  ) : (
                    <Count value={String(card.value)} />
                  )}
                </strong>
                <span className={styles.cardNote}>{card.note}</span>
              </Link>
            </li>
          ))}
      </ul>
    </section>
  );
}

/** "Missed call 30 min ago · 2 calls · call back", as their row on Leads says it. */
export function missedLine(
  at: string,
  calls: number,
  now: Date = new Date(),
): string {
  return `Missed call ${ago(at, now)}${calls > 1 ? ` · ${calls} calls` : ""} · call back`;
}

/** 3. One customer to call next, with one clear action (items 13-15). */
export function NextCall({ side, own }: { side: Side; own: HomeSide | null }) {
  const cold = side === "cold";
  const lead = own?.next_lead ?? null;
  // One who rang and wasn't reached comes first, and says so, as on Leads
  // (Leads 2, 1 Nov 2026: a missed call not yet returned is To Call's first row).
  const missed = lead?.missed_at
    ? missedLine(lead.missed_at, lead.missed_calls ?? 0)
    : null;
  return (
    <section className={styles.next} aria-labelledby="next-title">
      <div className={styles.nextBody}>
        <p id="next-title" className={styles.kicker}>
          {cold ? "Next cold call" : "Next inbound call"}
        </p>
        {lead ? (
          <>
            <Link
              className={styles.nextName}
              href={`/leads?lead=${lead.lead_id}`}
            >
              {displayName(lead.name)}
            </Link>
            <p className={styles.nextWhy}>
              {[
                lead.source_label,
                // A Cold lead nobody has called is Unworked (QA, 31 Oct 2026).
                missed ??
                  (cold && lead.why === "New lead" ? "Unworked" : lead.why),
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            <Link
              className={styles.callNow}
              href={leadsHref(side, { view: "to_call" })}
              // Start cold calling opens a round at this card and dials nothing
              // until Call (ph2-33: backing out of the dialler left a phantom
              // call); a call-back or an Inbound lead dials at once.
              onClick={() =>
                cold && !missed
                  ? handOverRound(lead.lead_id)
                  : handOverLead(lead.lead_id, true)
              }
            >
              <PhoneCall size={18} aria-hidden="true" />
              {missed
                ? `Call ${displayName(lead.name).split(" ")[0]} back`
                : cold
                  ? "Start Cold Calling"
                  : `Call ${displayName(lead.name).split(" ")[0]} now`}
            </Link>
          </>
        ) : (
          <p className={styles.quiet}>
            {cold
              ? "No cold leads to call right now."
              : "No new leads right now."}
          </p>
        )}
      </div>
    </section>
  );
}

/** 4. Up to three of today's tasks, + Add and See all (items 18-24). */
export function TodayTasks({
  tasks,
  failed,
  onDone,
  onRetry,
  onAdded,
  title = "Today's tasks",
  side = "inbound",
  onMoved,
}: {
  tasks: ListedTask[] | null;
  /** The side whose next call an empty block offers. */
  side?: Side;
  /** A task moved to another time: read the list again. */
  onMoved?: () => void;
  failed: boolean;
  onDone: (task: ListedTask) => void;
  onRetry: () => void;
  onAdded: () => void;
  /** "My tasks" on the owner's Team Home. */
  title?: string;
}) {
  const [adding, setAdding] = useState(false);
  const [later, setLater] = useState<ListedTask | null>(null);
  const move = async (task: ListedTask, time: Later) => {
    setLater(null);
    try {
      const saved = await snoozeTask(task, SNOOZE[time]);
      notify({
        id: "home-later",
        tone: "success",
        title: `Moved to ${whenDay(saved.starts_at)}`,
        timeout: 3000,
      });
      onMoved?.();
    } catch {
      notify({
        id: "home-later",
        tone: "error",
        title: "Not moved",
        message: "Try again.",
      });
    }
  };
  return (
    <section className={styles.block} aria-labelledby="tasks-title">
      <Head id="tasks-title" title={title}>
        <button
          type="button"
          className={styles.addTask}
          onClick={() => setAdding(true)}
        >
          + Add
        </button>
        <SeeAll href="/leads?tab=tasks" />
      </Head>
      {failed ? (
        <p className={styles.quiet} role="alert">
          Tasks didn&apos;t load.{" "}
          <button type="button" className={styles.retry} onClick={onRetry}>
            Try again
          </button>
        </p>
      ) : tasks === null ? (
        <p className={styles.quiet} role="status">
          Loading tasks…
        </p>
      ) : tasks.length ? (
        <ul className={styles.rows}>
          {[...tasks]
            // Late first, in red: Tasks' own overdue (competitor teardown #1).
            .sort((a, b) => Number(late(b)) - Number(late(a)))
            .slice(0, 3)
            .map((task) => (
              <SwipeRow
                key={task.task_id}
                className={styles.taskRow}
                done="Done"
                late={late(task)}
                onDone={task.status === "done" ? undefined : () => onDone(task)}
                onLater={
                  task.status === "done" ? undefined : () => setLater(task)
                }
              >
                {/* A 44 px target around the box (QA, 31 Oct 2026). */}
                <label className={styles.check}>
                  <input
                    type="checkbox"
                    aria-label={`Done: ${task.title}`}
                    checked={task.status === "done"}
                    onChange={() => onDone(task)}
                  />
                  <span className={styles.box} aria-hidden="true">
                    <Check size={14} strokeWidth={3} />
                  </span>
                </label>
                <span className={styles.rowText}>
                  <strong>{task.title}</strong>
                  <span className={styles.taskMeta}>
                    {when(task.starts_at) ? (
                      <span data-late-time={late(task) || undefined}>
                        {when(task.starts_at)}
                      </span>
                    ) : null}
                    {tagOf(task) ? (
                      <span className={styles.tag} data-tag={tagOf(task)}>
                        {TAG_WORDS[tagOf(task) as TaskTag]}
                      </span>
                    ) : null}
                    {task.lead_id && task.lead_name ? (
                      <Link href={`/leads?lead=${task.lead_id}`}>
                        {displayName(task.lead_name)}
                      </Link>
                    ) : null}
                  </span>
                </span>
              </SwipeRow>
            ))}
        </ul>
      ) : (
        <AllClear side={side} />
      )}
      <LaterSheet
        open={later !== null}
        title={later?.title ?? ""}
        onClose={() => setLater(null)}
        onPick={(time) => {
          if (later) void move(later, time);
        }}
      />
      <AddTaskSheet
        open={adding}
        onClose={() => setAdding(false)}
        onAdded={() => {
          setAdding(false);
          onAdded();
        }}
      />
    </section>
  );
}

/** A task's snooze for each of the after-call's times. */
const SNOOZE: Record<Later, TaskSnoozeChoice> = {
  hour: "1h",
  evening: "evening",
  morning: "tomorrow",
  week: "week",
};

/** Past its time and not done: Tasks' own overdue. */
const late = (task: ListedTask) =>
  task.status !== "done" && task.overdue === true;

/** An empty block: one line, and the next thing to do, never a dead end
 *  (competitor teardown #1, 1 Nov 2026). */
function AllClear({ side }: { side: Side }) {
  return (
    <p className={styles.allClear}>
      <span>All clear</span>
      <Link
        className={styles.nextAction}
        href={leadsHref(side, { view: "to_call" })}
      >
        {side === "cold" ? "Start Cold Calling" : "Call your next lead"}
        <ChevronRight size={16} aria-hidden="true" />
      </Link>
    </p>
  );
}

type Upcoming = HomeSide["upcoming"][number];

/** One follow-up: swipe right calls it (its after-call says what happened),
 *  left moves it. */
function FollowRow({
  lead,
  side,
  onLater,
}: {
  lead: Upcoming;
  side: Side;
  onLater: (lead: Upcoming) => void;
}) {
  const call = useRef<HTMLAnchorElement>(null);
  return (
    <SwipeRow
      className={styles.followRow}
      done="Call"
      onDone={() => call.current?.click()}
      onLater={() => onLater(lead)}
    >
      <Link className={styles.rowText} href={`/leads?lead=${lead.lead_id}`}>
        <strong>{displayName(lead.name)}</strong>
        <span>
          {[
            lead.next_action_note || lead.stage_label,
            whenDay(lead.next_action_at),
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </Link>
      <Link
        ref={call}
        className={styles.phone}
        href={leadsHref(side, { view: "follow_ups", when: "upcoming" })}
        aria-label={`Call ${displayName(lead.name)}`}
        onClick={() => handOverLead(lead.lead_id, true)}
      >
        <Phone size={18} aria-hidden="true" />
      </Link>
    </SwipeRow>
  );
}

/** 5. The next two follow-ups, See all for the rest (items 26-28). */
export function UpcomingFollowUps({
  side,
  own,
}: {
  side: Side;
  own: HomeSide | null;
}) {
  const [later, setLater] = useState<Upcoming | null>(null);
  // Moved here: off this list at once, while Home reads again.
  const [moved, setMoved] = useState<string[]>([]);
  const rows = (own?.upcoming ?? []).filter(
    (lead) => !moved.includes(lead.lead_id),
  );
  const move = async (lead: Upcoming, time: Later) => {
    setLater(null);
    const at = nextCallTime(time);
    try {
      await setFollowUp(lead, at);
      setMoved((ids) => [...ids, lead.lead_id]);
      notify({
        id: "home-later",
        tone: "success",
        title: `Moved to ${whenDay(at.toISOString())}`,
        timeout: 3000,
      });
      retryHome();
    } catch {
      notify({
        id: "home-later",
        tone: "error",
        title: "Not moved",
        message: "Try again.",
      });
    }
  };
  return (
    <section className={styles.block} aria-labelledby="follow-ups-title">
      <Head id="follow-ups-title" title="Upcoming follow-ups">
        <SeeAll
          href={leadsHref(side, { view: "follow_ups", when: "upcoming" })}
        />
      </Head>
      {rows.length ? (
        <ul className={styles.rows}>
          {rows.slice(0, 2).map((lead) => (
            <FollowRow
              key={lead.lead_id}
              lead={lead}
              side={side}
              onLater={setLater}
            />
          ))}
        </ul>
      ) : (
        <AllClear side={side} />
      )}
      <LaterSheet
        open={later !== null}
        title={later ? displayName(later.name) : ""}
        onClose={() => setLater(null)}
        onPick={(time) => {
          if (later) void move(later, time);
        }}
      />
    </section>
  );
}

/** 6. The last three calls, each with its outcome and time (Dipak's
 *  picture): Calls has the rest. */
export function RecentCalls() {
  const [week, retry] = useWeekActivity();
  const [now] = useState(() => new Date());
  if (week.status === "off") return null;
  const rows =
    week.status === "ready"
      ? weekCalls(week.items)
          .slice(0, 3)
          .map((item) => ({
            ...rowFromActivity(item),
            line: outcomeLine(item.event),
            // Outcome and time only, never the capture line: Calls has it
            // with its fix (production report 146).
            talked: false,
          }))
      : [];
  return (
    <section className={styles.block} aria-labelledby="recent-title">
      <Head id="recent-title" title="Recent calls">
        <SeeAll href="/analysis/calls" />
      </Head>
      {week.status === "loading" ? (
        <CallRowsSkeleton label="Recent calls" />
      ) : week.status === "error" ? (
        <p className={styles.quiet} role="alert">
          Calls didn&apos;t load.{" "}
          <button type="button" className={styles.retry} onClick={retry}>
            Try again
          </button>
        </p>
      ) : rows.length ? (
        <CallRows rows={rows} now={now} label="Recent calls" days={false} />
      ) : (
        <p className={styles.quiet}>No calls yet this week.</p>
      )}
    </section>
  );
}

/** 7. Today's numbers on this side, two by two (Dipak's picture). */
/** Whether this phone app reads its call history: false in an app version
 *  that can't yet; null in a browser, or until the phone answers. */
function useCallHistory(): boolean | null {
  const [readable, setReadable] = useState<boolean | null>(null);
  useEffect(() => {
    if (!inPhoneApp()) return;
    let alive = true;
    void callLogStatus().then((status) => {
      if (alive) setReadable(status !== null);
    });
    return () => {
      alive = false;
    };
  }, []);
  return readable;
}

export function TodayPerformance({
  side,
  own,
}: {
  side: Side;
  own: HomeSide | null;
}) {
  const numbers = own?.numbers;
  const readable = useCallHistory();
  const calls = `/analysis/calls?day=today&side=${side}`;
  // A call whose outcome the phone never told us is neither connected nor
  // not, and talk time says what measured it (owner and Dipak, 2 Nov 2026);
  // every number opens the calls it counts.
  const unknown = numbers?.unknown ?? 0;
  const talked = numbers?.talk_seconds ?? 0;
  const recorded = numbers?.talk_recorded_seconds;
  const figures = [
    { label: "Attempted", value: numbers?.calls, href: calls },
    unknown && numbers
      ? {
          label: "Outcome known",
          value: numbers.calls - unknown,
          href: `${calls}&outcome=known`,
        }
      : {
          label: "Connected",
          value: numbers?.connected,
          href: `${calls}&outcome=connected`,
        },
    {
      label:
        !talked || recorded === undefined
          ? "Talk time"
          : recorded === talked
            ? "Talk · recordings"
            : recorded
              ? "Talk time"
              : "Talk · call history",
      value: numbers
        ? talkOrDash(
            numbers.talk_seconds,
            numbers.talk_estimated_seconds,
            (seconds) => breakLength(Math.round(seconds / 60)),
          )
        : null,
      href: `${calls}&outcome=connected`,
    },
    {
      label: "Follow-ups done",
      value: numbers?.follow_ups_done,
      href: leadsHref(side, { view: "follow_ups", when: "today" }),
    },
  ];
  return (
    <section className={styles.block} aria-labelledby="performance-title">
      <Head id="performance-title" title="Today's performance">
        <Link className={styles.seeAll} href="/growth">
          See details
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </Head>
      <div className={styles.figures}>
        <p className={styles.figuresNote}>
          {side === "cold" ? "Cold calls only" : "Inbound calls only"} · Today
        </p>
        <ul>
          {figures.map((figure) => (
            <li key={figure.label}>
              <Link href={figure.href}>
                <span>{figure.label}</span>
                <strong>{figure.value ?? " "}</strong>
              </Link>
            </li>
          ))}
        </ul>
      </div>
      {unknown && readable === false ? (
        <p className={styles.quiet}>
          Call history isn&apos;t available in this app version yet
        </p>
      ) : null}
    </section>
  );
}

/** The six blocks for one seller's day, in the handoff's order. */
export function SellerBlocks({
  desk,
  side,
  onSide,
  access: given,
}: {
  desk: HomeDesk;
  side: Side;
  onSide: (side: Side) => void;
  /** Which sides this seller works, when the page read them beside the desk. */
  access?: SidesAccess | null;
}) {
  const fetched = useSidesAccess(given === undefined);
  const access = given === undefined ? fetched : given;
  const { tasks, failed, reload, done } = useTaskList();
  // Only the type this seller works when they don't have both.
  const shown: Side =
    access && !access.inbound && access.cold
      ? "cold"
      : access && access.inbound && !access.cold
        ? "inbound"
        : side;
  const own = desk.sides?.[shown] ?? null;
  const go = useGo();
  return (
    <div className={styles.me}>
      {/* A call still waiting for its answer comes first, as on Leads (teardown
          3: an answer is never lost); Finish opens it at its question there. */}
      <div data-area="finish">
        <FinishRow
          calls={desk.unanswered}
          onFinish={(leadId) => {
            handOverAnswer(leadId);
            go("/leads");
          }}
        />
      </div>
      {access ? (
        <div data-area="side">
          <SideBlock
            side={shown}
            access={access}
            own={own}
            inbound={desk.sides?.inbound ?? null}
            onSide={onSide}
          />
        </div>
      ) : null}
      <div data-area="cards">
        <TodayCards
          side={shown}
          own={own}
          tasks={
            tasks ? tasks.filter((task) => task.status !== "done").length : null
          }
        />
      </div>
      <div data-area="next">
        <NextCall side={shown} own={own} />
      </div>
      <div data-area="tasks">
        <TodayTasks
          tasks={tasks}
          failed={failed}
          onDone={done}
          onRetry={reload}
          onAdded={reload}
          side={shown}
          onMoved={reload}
        />
      </div>
      <div data-area="follow">
        <UpcomingFollowUps side={shown} own={own} />
      </div>
      <div data-area="recent">
        <RecentCalls />
      </div>
      <div data-area="perf">
        <TodayPerformance side={shown} own={own} />
      </div>
    </div>
  );
}

/** The owner's own work on the Team Home: three of today's tasks and the next
 *  two follow-ups on the side shown (Dipak: owners have their tasks too). */
export function MyTasks({ desk, side }: { desk: HomeDesk; side: Side }) {
  const { tasks, failed, reload, done } = useTaskList();
  return (
    <>
      <TodayTasks
        title="My tasks"
        tasks={tasks}
        failed={failed}
        onDone={done}
        onRetry={reload}
        onAdded={reload}
        side={side}
        onMoved={reload}
      />
      <UpcomingFollowUps side={side} own={desk.sides?.[side] ?? null} />
    </>
  );
}
