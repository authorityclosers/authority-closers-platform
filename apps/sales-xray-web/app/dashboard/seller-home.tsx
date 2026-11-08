"use client";

/**
 * A seller's Home, as Dipak's picture (owner order, 2 Nov 2026,
 * docs/handoffs/dipak-home-20261102; his own design, 4 Nov 2026): the work to
 * do. Each block below stands alone, in the picture's order:
 *  0. Pending action: a call still waiting for its answer, only while one is.
 *  1. Inbound Leads | Cold Leads, only for someone with both; on Cold, one row
 *     when fresh inbound leads wait.
 *  2. Today's overview: New leads (Inbound) or Unworked leads (Cold), Open
 *     leads, Follow-ups (the side's own) and Tasks (shared, never a call),
 *     each with one caption. Each tile opens the exact Leads list it counts.
 *  3. Next action: one customer, and Call now or Start Cold Calling.
 *  4. Today's tasks: three at most, See all.
 *  5. Upcoming follow-ups: two at most, each with its call button, See all.
 *  6. Recent calls: the last three, each with its outcome and time, never the
 *     capture line (Calls has it, with its fix).
 *  7. Today's performance: two by two (Attempted, Connected, Talk time,
 *     Follow-ups done), each opening the calls or follow-ups it counts.
 * The desk carries both sides, so the selector switches with no second read.
 */

import { ArrowRight, Check, ChevronRight, Phone, RotateCw } from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type HTMLAttributes,
  type ReactNode,
} from "react";

import { displayName } from "../display-name";
import { ActionSheet } from "../leads/action-sheet";
import { AddTaskSheet } from "../leads/add-task-sheet";
import { useRowGestures } from "../leads/gestures";
import {
  CallRows,
  outcomeLine,
  rowFromActivity,
  useGo,
  useWeekActivity,
  weekCalls,
} from "../calls/call-rows";
import { CallRowsSkeleton } from "../calls/phone-calls";
import { readGone } from "../leads/finish-row";
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
  type Unanswered,
} from "../leads/leads-client";
import { callLogStatus, inPhoneApp } from "../leads/native-phone";
import { notify } from "../notice-center";
import { CallLens } from "../ui/call-lens/call-lens";
import { SideSelector, type Side } from "../ui/side-selector";
import { SlotLayout } from "../ui/slots/slot-layout";
import { SELLER_HOME } from "./home-slots/plans";
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

/** The Follow-ups list a follow-up sits in: Due Today until midnight, then
 *  Upcoming (bug report #92: Home's next follow-ups run from now, so one later
 *  today opened Upcoming, which starts tomorrow, and the list was empty). */
export const followUpsDay = (at: string | null): "today" | "upcoming" =>
  at && IST_DATE.format(new Date(at)) <= IST_DATE.format(new Date())
    ? "today"
    : "upcoming";

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
      <ArrowRight size={16} aria-hidden="true" />
    </Link>
  );
}

const never = () => () => undefined;

/** 0. Pending action (Dipak's design, 4 Nov 2026): the newest call still
 *  waiting for its answer, on its own card, only while one waits. A call put
 *  away on Leads ("Didn't call") stays away here too. */
export function PendingAction({
  calls,
  onFinish,
  now = new Date(),
}: {
  calls: readonly Unanswered[] | null | undefined;
  /** Opens the lead on "How did the call go?". */
  onFinish: (leadId: string) => void;
  now?: Date;
}) {
  const hydrated = useSyncExternalStore(
    never,
    () => true,
    () => false,
  );
  if (!hydrated) return null;
  const gone = readGone();
  const waiting = (calls ?? []).filter((call) => !gone.includes(call.event_id));
  const call = waiting[0];
  if (!call) return null;
  return (
    <section className={styles.pending} aria-labelledby="pending-title">
      <div className={styles.pendingHead}>
        <h2 id="pending-title">Pending action</h2>
        <span className={styles.chip} data-tone="warn">
          {`${waiting.length} ${waiting.length === 1 ? "reminder" : "reminders"}`}
        </span>
      </div>
      <p className={styles.pendingLine}>
        {`${displayName(call.name)} · Last dialled ${ago(call.called_at, now)}`}
      </p>
      <button
        type="button"
        className={styles.pendingGo}
        onClick={() => onFinish(call.lead_id)}
      >
        Complete call activity
        <ChevronRight size={18} aria-hidden="true" />
      </button>
    </section>
  );
}

/** Dipak's figures read as two digits: 02, 00; 12 and 229 as they are. */
export const twoDigits = (value: number) => String(value).padStart(2, "0");

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
  failed = false,
}: {
  side: Side;
  own: HomeSide | null;
  tasks: number | null;
  /** The leads didn't load: every card keeps its place and says "–", never
   *  a 0 it doesn't know (honest numbers, 3 Nov 2026). */
  failed?: boolean;
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
      note: "Needs discussion",
      value: counts?.open_leads,
      href: leadsHref(side, {
        view: "all",
        step: own?.open_key ?? "open_leads",
      }),
    },
    {
      key: "follow_ups",
      label: "Follow-ups",
      note: "Due today",
      value: counts?.follow_ups_today,
      href: leadsHref(side, { view: "follow_ups", when: "today" }),
    },
    {
      key: "tasks",
      label: "Tasks",
      note: "Due today",
      value: tasks,
      href: "/leads?tab=tasks",
    },
  ];
  return (
    <section className={styles.block} aria-labelledby="today-title">
      <div className={styles.overview}>
        <h2 id="today-title">Today&apos;s overview</h2>
        <p>{cold ? "Your cold lead activity" : "Your inbound lead activity"}</p>
      </div>
      <ul className={styles.cards}>
        {cards
          // A card whose stage the organisation doesn't have is left
          // out, never a raw "open_leads" (phone personas, 31 Oct 2026).
          .filter(
            (card) =>
              !(own && card.key === "new" && own.new_key === null) &&
              !(own && card.key === "open" && own.open_key === null),
          )
          .map((card) => {
            const unknown = failed && card.value == null;
            const body = (
              <>
                <span className={styles.cardLabel}>{card.label}</span>
                <strong
                  aria-busy={(!unknown && card.value == null) || undefined}
                  data-unknown={unknown || undefined}
                >
                  {unknown ? (
                    "–"
                  ) : card.value == null ? (
                    " "
                  ) : (
                    <Count value={twoDigits(card.value)} />
                  )}
                </strong>
                <span className={styles.cardNote}>{card.note}</span>
              </>
            );
            return (
              <li key={card.key}>
                {unknown ? (
                  <div className={styles.card} data-card={card.key}>
                    {body}
                  </div>
                ) : (
                  <Link
                    className={styles.card}
                    href={card.href}
                    data-card={card.key}
                  >
                    {body}
                  </Link>
                )}
              </li>
            );
          })}
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

/** 3. One customer to call next, with one clear action (items 13-15). Its
 *  Call is the Call lens (L0 brief); a hold on the card offers Call, Open
 *  lead and Later, as a hold on a Leads row does. While Home reads, and when
 *  the read fails, the card keeps its place and its size. */
export function NextCall({
  side,
  own,
  state = "ready",
}: {
  side: Side;
  own: HomeSide | null;
  state?: "ready" | "loading" | "error";
}) {
  const cold = side === "cold";
  const lead = state === "ready" ? (own?.next_lead ?? null) : null;
  const [held, setHeld] = useState(false);
  const [later, setLater] = useState(false);
  const go = useGo();
  const { bind } = useRowGestures({
    onHold: lead ? () => setHeld(true) : undefined,
  });
  // One who rang and wasn't reached comes first, and says so, as on Leads
  // (Leads 2, 1 Nov 2026: a missed call not yet returned is To Call's first row).
  const missed = lead?.missed_at
    ? missedLine(lead.missed_at, lead.missed_calls ?? 0)
    : null;
  const name = lead ? displayName(lead.name) : "";
  const callTo = leadsHref(side, { view: "to_call" });
  // Start cold calling opens a round at this card and dials nothing until
  // Call (ph2-33: backing out of the dialler left a phantom call); a
  // call-back or an Inbound lead dials at once.
  const call = () =>
    lead &&
    (cold && !missed
      ? handOverRound(lead.lead_id)
      : handOverLead(lead.lead_id, true));
  const move = async (time: Later) => {
    setLater(false);
    if (!lead) return;
    const at = nextCallTime(time);
    try {
      await setFollowUp(lead, at);
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
    <>
      <section
        className={styles.next}
        aria-labelledby="next-title"
        aria-busy={state === "loading" || undefined}
        {...(bind as unknown as HTMLAttributes<HTMLElement>)}
      >
        <div className={styles.nextHead}>
          <h2 id="next-title">Next action</h2>
          {lead ? (
            <span className={styles.chip} data-tone="good">
              Ready to call
            </span>
          ) : null}
        </div>
        {state === "loading" ? (
          <>
            <span className={styles.nextName} data-wait="" aria-hidden="true" />
            <span className={styles.nextWhy} data-wait="" aria-hidden="true" />
            <span className={styles.slot} data-wait="" aria-hidden="true" />
          </>
        ) : state === "error" ? (
          <>
            <p className={styles.nextName}>Leads didn&apos;t load</p>
            <p className={styles.nextWhy}>
              Your numbers show again once they do.
            </p>
            <button type="button" className={styles.tonal} onClick={retryHome}>
              <RotateCw size={18} aria-hidden="true" />
              Try again
            </button>
          </>
        ) : lead ? (
          <>
            <Link
              className={styles.nextName}
              href={`/leads?lead=${lead.lead_id}`}
            >
              {name}
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
            <CallLens href={callTo} onClick={call}>
              {missed ? "Call back" : cold ? "Start Cold Calling" : "Call now"}
            </CallLens>
          </>
        ) : (
          <>
            <p className={styles.nextName}>
              {cold
                ? "No cold leads to call right now"
                : "No new leads right now"}
            </p>
            <p className={styles.nextWhy}>New ones show here as they come.</p>
            <Link className={styles.tonal} href={leadsHref(side, {})}>
              Open Leads
            </Link>
          </>
        )}
      </section>
      {lead ? (
        <>
          <ActionSheet
            open={held}
            title={name}
            sub="Next action"
            onClose={() => setHeld(false)}
          >
            <div className={styles.laterTimes}>
              <button
                type="button"
                className={styles.laterTime}
                onClick={() => {
                  setHeld(false);
                  call();
                  go(callTo);
                }}
              >
                {missed
                  ? "Call back"
                  : cold
                    ? "Start Cold Calling"
                    : "Call now"}
              </button>
              <button
                type="button"
                className={styles.laterTime}
                onClick={() => {
                  setHeld(false);
                  go(`/leads?lead=${lead.lead_id}`);
                }}
              >
                Open lead
              </button>
              <button
                type="button"
                className={styles.laterTime}
                onClick={() => {
                  setHeld(false);
                  setLater(true);
                }}
              >
                Later
              </button>
            </div>
          </ActionSheet>
          <LaterSheet
            open={later}
            title={name}
            onClose={() => setLater(false)}
            onPick={(time) => void move(time)}
          />
        </>
      ) : null}
    </>
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
  canAdd = true,
}: {
  tasks: ListedTask[] | null;
  /** + Add beside See all: the owner's Team Home keeps it; a seller's Home
   *  adds from the + above (Dipak's design, 4 Nov 2026). */
  canAdd?: boolean;
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
        {canAdd ? (
          <button
            type="button"
            className={styles.addTask}
            onClick={() => setAdding(true)}
          >
            + Add
          </button>
        ) : null}
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
        <ul className={`${styles.rows} ${styles.taskList}`}>
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
                {late(task) ? (
                  <span className={styles.chip} data-tone="warn">
                    Overdue
                  </span>
                ) : null}
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
        href={leadsHref(side, {
          view: "follow_ups",
          when: followUpsDay(lead.next_action_at),
        })}
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
        {/* Every follow-up: the next two can be later today and tomorrow,
            which are two of its lists (bug report #92). */}
        <SeeAll href={leadsHref(side, { view: "follow_ups" })} />
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

/** The calls on one side's leads, or all of them without a side (Swamini,
 *  4 Nov 2026, #170: Inbound's Recent calls listed Cold calls); a lead with
 *  no side is Inbound, as on the server. */
export function onSide<T extends { side?: Side | null }>(
  items: T[],
  side: Side | null,
): T[] {
  return side
    ? items.filter((item) => (item.side ?? "inbound") === side)
    : items;
}

/** 6. The last three calls, each with its outcome and time (Dipak's
 *  picture): Calls has the rest. */
export function RecentCalls({ side = null }: { side?: Side | null }) {
  const [week, retry] = useWeekActivity();
  const [now] = useState(() => new Date());
  if (week.status === "off") return null;
  const rows =
    week.status === "ready"
      ? onSide(weekCalls(week.items), side)
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
  other = null,
}: {
  side: Side;
  own: HomeSide | null;
  /** The other side's numbers: when this side has no call today and that one
   *  has, a line says so (#170: Inbound's Attempted 0 beside Cold calls). */
  other?: HomeSide | null;
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
      {numbers && !numbers.calls && other?.numbers?.calls ? (
        <p className={styles.quiet}>
          {`${other.numbers.calls} tried on ${side === "cold" ? "Inbound" : "Cold"} today`}
        </p>
      ) : null}
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
  state = "ready",
}: {
  /** Null while Home reads, or when the read failed. */
  desk: HomeDesk | null;
  side: Side;
  onSide: (side: Side) => void;
  /** Which sides this seller works, when the page read them beside the desk. */
  access?: SidesAccess | null;
  /** Loading and error draw the top four blocks in their final places and
   *  sizes, so nothing moves when the desk arrives (FRAMEWORK L6). */
  state?: "ready" | "loading" | "error";
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
  const own = desk?.sides?.[shown] ?? null;
  const go = useGo();
  const ready = desk !== null && state === "ready";
  return (
    <SlotLayout
      plan={SELLER_HOME}
      className={styles.me}
      blocks={{
        // A call still waiting for its answer comes first, as on Leads
        // (teardown 3: an answer is never lost); Finish opens it at its
        // question there.
        finish: desk ? (
          <PendingAction
            calls={desk.unanswered}
            onFinish={(leadId) => {
              handOverAnswer(leadId);
              go("/leads");
            }}
          />
        ) : null,
        side: access ? (
          <SideBlock
            side={shown}
            access={access}
            own={own}
            inbound={desk?.sides?.inbound ?? null}
            onSide={onSide}
          />
        ) : null,
        cards: (
          <TodayCards
            side={shown}
            own={own}
            failed={state === "error"}
            tasks={
              ready && tasks
                ? tasks.filter((task) => task.status !== "done").length
                : null
            }
          />
        ),
        next: (
          <NextCall side={shown} own={own} state={ready ? "ready" : state} />
        ),
        tasks: ready ? (
          <TodayTasks
            tasks={tasks}
            failed={failed}
            onDone={done}
            onRetry={reload}
            onAdded={reload}
            side={shown}
            onMoved={reload}
            canAdd={false}
          />
        ) : null,
        follow: ready ? <UpcomingFollowUps side={shown} own={own} /> : null,
        recent: ready ? <RecentCalls side={shown} /> : null,
        perf: ready ? (
          <TodayPerformance
            side={shown}
            own={own}
            other={desk?.sides?.[shown === "cold" ? "inbound" : "cold"] ?? null}
          />
        ) : null,
      }}
    />
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
