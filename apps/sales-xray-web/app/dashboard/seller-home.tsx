"use client";

/**
 * A seller's Home (Dipak's Home + Leads handoff, 31 Oct 2026, pages 4-5 and
 * 12, items 01-35): the work to do, not the history. Recent calls live in
 * Reports and on each lead. Each block below stands alone, in the handoff's
 * order:
 *  1. Inbound Leads | Cold Leads, only for someone with both; on Cold, a line
 *     when fresh inbound enquiries wait.
 *  2. Today: New leads (Inbound) or Unworked (Cold), Open leads, Follow-ups
 *     today (the side's own) and Tasks today (shared, never a call). Each
 *     card opens the exact Leads list it counts.
 *  3. Next to call: one customer, and Call now or Start cold calling.
 *  4. Today's tasks: three at most, + Add, See all.
 *  5. Upcoming follow-ups: two at most, See all.
 *  6. Today's performance: one row (Tried, Connected, Talk time, F/U done).
 * The desk carries both sides, so the selector switches with no second read.
 */

import { ChevronRight, Phone, PhoneCall } from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { displayName } from "../display-name";
import { AddTaskSheet } from "../leads/add-task-sheet";
import { handOverLead } from "../leads/lead-handoff";
import {
  deskRequest,
  readTasks,
  taskAction,
  type ListedTask,
} from "../leads/leads-client";
import { SideSelector, type Side } from "../ui/side-selector";
import { breakLength } from "./home-today";
import {
  Count,
  MetricPager,
  MoreFigures,
  minutes,
  share,
} from "./metric-pager";
import type { HomeBreak, HomeDesk, HomeSide } from "./my-day-client";
import styles from "./seller-home.module.css";

/** Which lead types this seller works: GET /sides (Leads session, 31 Oct). */
type SidesAccess = { inbound: boolean; cold: boolean };

/** Both types, until an owner access setting exists (handoff: owner decides). */
export function useSidesAccess(): SidesAccess | null {
  const [access, setAccess] = useState<SidesAccess | null>(null);
  useEffect(() => {
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
  }, []);
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
  return { tasks, failed: today.failed, reload: today.reload, done };
}

/** Today's tasks that aren't calls: a follow-up is counted under Follow-ups. */
export function useTodayTasks(): {
  tasks: ListedTask[] | null;
  failed: boolean;
  setTasks: (next: ListedTask[]) => void;
  reload: () => void;
} {
  const [tasks, setTasks] = useState<ListedTask[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      readTasks("overdue", controller.signal),
      readTasks("today", controller.signal),
    ]).then(
      ([late, today]) =>
        setTasks(
          [...(late?.tasks ?? []), ...(today?.tasks ?? [])]
            .filter((task) => task.kind !== "call_back")
            .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at)),
        ),
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
  return { tasks, failed, setTasks, reload };
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
      <SideSelector
        value={side}
        onChange={onSide}
        notes={{
          inbound:
            "Fresh enquiries from ads, your website and other inbound sources",
          cold: "Your assigned cold prospecting list",
        }}
      />
      {waiting > 0 && own ? (
        <Link
          className={styles.alert}
          href={leadsHref("inbound", { view: "to_call", step: "new" })}
        >
          {`${waiting} fresh inbound ${waiting === 1 ? "enquiry needs" : "enquiries need"} attention`}
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
  extras,
}: {
  side: Side;
  own: HomeSide | null;
  tasks: number | null;
  extras?: ReactNode;
}) {
  const cold = side === "cold";
  const counts = own?.counts;
  const cards = [
    {
      key: "new",
      label: cold ? "Unworked" : "New leads",
      note: cold ? "Never attempted" : "First call pending",
      value: counts?.new,
      href: leadsHref(side, { view: "to_call", step: own?.new_key ?? "new" }),
    },
    {
      key: "open",
      label: "Open leads",
      note: "Further discussion",
      value: counts?.open_leads,
      href: leadsHref(side, {
        view: "all",
        step: own?.open_key ?? "open_leads",
      }),
    },
    {
      key: "follow_ups",
      label: "Follow-ups today",
      note: "Scheduled contacts",
      value: counts?.follow_ups_today,
      href: leadsHref(side, { view: "follow_ups", when: "today" }),
    },
    {
      key: "tasks",
      label: "Tasks today",
      note: "Shared work list",
      value: tasks,
      href: "/leads?tab=tasks",
    },
  ];
  return (
    <section className={styles.block} aria-labelledby="today-title">
      <Head id="today-title" title="Today">
        <span className={styles.sideWord}>
          {cold ? "Cold work" : "Inbound work"}
        </span>
        {extras}
      </Head>
      <MetricPager
        label="Your numbers"
        pages={[
          {
            key: "today",
            label: "Your work",
            content: (
              <ul className={styles.cards}>
                {cards.map((card) => (
                  <li key={card.key}>
                    <Link
                      className={styles.card}
                      href={card.href}
                      data-card={card.key}
                      aria-description={card.note}
                    >
                      <span className={styles.cardLabel}>{card.label}</span>
                      <strong aria-busy={card.value == null || undefined}>
                        {card.value == null ? (
                          " "
                        ) : (
                          <Count value={String(card.value)} />
                        )}
                      </strong>
                    </Link>
                  </li>
                ))}
              </ul>
            ),
          },
          {
            key: "more",
            label: "Your calls",
            content: (
              <MoreFigures
                figures={[
                  {
                    label: "Connection rate",
                    value: own
                      ? share(own.numbers.connected, own.numbers.calls)
                      : null,
                  },
                  {
                    label: "Talk time",
                    value: own ? minutes(own.numbers.talk_seconds) : null,
                  },
                  {
                    label: "Called today",
                    value: own ? String(own.to_call_today.called) : null,
                  },
                  {
                    label: "Follow-ups done",
                    value: own ? String(own.numbers.follow_ups_done) : null,
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </section>
  );
}

/** 3. One customer to call next, with one clear action (items 13-15). */
export function NextCall({ side, own }: { side: Side; own: HomeSide | null }) {
  const cold = side === "cold";
  const lead = own?.next_lead ?? null;
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
                cold && lead.why === "New lead" ? "Unworked" : lead.why,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            <Link
              className={styles.callNow}
              href={leadsHref(side, { view: "to_call" })}
              onClick={() => handOverLead(lead.lead_id, true)}
            >
              <PhoneCall size={18} aria-hidden="true" />
              {cold
                ? "Start cold calling"
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
      {own && !cold ? (
        <Countdown
          left={own.to_call_today.left}
          called={own.to_call_today.called}
        />
      ) : null}
    </section>
  );
}

const RING = 2 * Math.PI * 26;

/** Today's countdown (Dipak, item 12): the leads still to call today, the
 *  ring filling as calls are made. */
function Countdown({ left, called }: { left: number; called: number }) {
  const whole = left + called;
  const done = whole ? called / whole : 0;
  return (
    <div
      className={styles.countdown}
      role="img"
      data-countdown=""
      aria-label={`${left} left to call today, ${called} called`}
    >
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <circle className={styles.ringTrack} cx="32" cy="32" r="26" />
        <circle
          className={styles.ringDone}
          cx="32"
          cy="32"
          r="26"
          style={
            {
              "--ring": RING,
              strokeDasharray: RING,
              strokeDashoffset: RING * (1 - done),
            } as CSSProperties
          }
        />
      </svg>
      <div className={styles.ringText} aria-hidden="true">
        <strong>{left}</strong>
        <span>left today</span>
      </div>
    </div>
  );
}

const CLOCK_SHORT = new Intl.DateTimeFormat("en-IN", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

/** My three longest breaks today (Dipak, item 36): red when nobody set them. */
export function LongestBreaks({
  breaks,
}: {
  breaks: readonly HomeBreak[] | null | undefined;
}) {
  return (
    <section className={styles.block} aria-labelledby="breaks-title">
      <Head id="breaks-title" title="Your longest breaks">
        <Link className={styles.seeAll} href="/growth">
          See all
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </Head>
      {breaks?.length ? (
        <ul className={styles.breaks}>
          {breaks.slice(0, 3).map((gap) => (
            <li
              key={gap.start}
              data-red={!gap.planned || undefined}
              title={gap.planned ? "Inside a set break" : "Not a set break"}
            >
              <span>
                {`${CLOCK_SHORT.format(new Date(gap.start))} – ${CLOCK_SHORT.format(new Date(gap.end))}`}
              </span>
              <strong>{breakLength(gap.minutes)}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.quiet}>No breaks yet today.</p>
      )}
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
}: {
  tasks: ListedTask[] | null;
  failed: boolean;
  onDone: (task: ListedTask) => void;
  onRetry: () => void;
  onAdded: () => void;
  /** "My tasks" on the owner's Team Home. */
  title?: string;
}) {
  const [adding, setAdding] = useState(false);
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
          {tasks.slice(0, 3).map((task) => (
            <li key={task.task_id} className={styles.taskRow}>
              <input
                type="checkbox"
                aria-label={`Done: ${task.title}`}
                checked={task.status === "done"}
                onChange={() => onDone(task)}
              />
              <span className={styles.rowText}>
                <strong>{task.title}</strong>
                <span className={styles.taskMeta}>
                  {when(task.starts_at) ? (
                    <span>{when(task.starts_at)}</span>
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
            </li>
          ))}
        </ul>
      ) : (
        <div className={styles.emptyTasks}>
          <span>No tasks today</span>
          <button
            type="button"
            className={styles.addTask}
            onClick={() => setAdding(true)}
          >
            + Add task
          </button>
        </div>
      )}
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

/** 5. The next two follow-ups, See all for the rest (items 26-28). */
export function UpcomingFollowUps({
  side,
  own,
}: {
  side: Side;
  own: HomeSide | null;
}) {
  const rows = own?.upcoming ?? [];
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
            <li key={lead.lead_id} className={styles.followRow}>
              <Link
                className={styles.rowText}
                href={`/leads?lead=${lead.lead_id}`}
              >
                <strong>{displayName(lead.name)}</strong>
                <span>
                  {[
                    lead.next_action_note || lead.stage_label,
                    when(lead.next_action_at),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </Link>
              <Link
                className={styles.phone}
                href={leadsHref(side, { view: "follow_ups", when: "upcoming" })}
                aria-label={`Call ${displayName(lead.name)}`}
                onClick={() => handOverLead(lead.lead_id, true)}
              >
                <Phone size={18} aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.quiet}>No follow-ups planned.</p>
      )}
    </section>
  );
}

/** 6. One compact row of today's numbers on this side (items 31-35). */
export function TodayPerformance({
  side,
  own,
}: {
  side: Side;
  own: HomeSide | null;
}) {
  const numbers = own?.numbers;
  const calls = `/analysis/calls?day=today${side === "cold" ? "&side=cold" : ""}`;
  const figures = [
    { label: "Tried", value: numbers?.calls, href: calls },
    {
      label: "Connected",
      value: numbers?.connected,
      href: `${calls}&outcome=connected`,
    },
    {
      label: "Talk time",
      value: numbers
        ? breakLength(Math.round(numbers.talk_seconds / 60))
        : null,
      href: "/growth",
    },
    {
      label: "F/U done",
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
      <ul className={styles.figures}>
        {figures.map((figure) => (
          <li key={figure.label}>
            <Link href={figure.href}>
              <strong>{figure.value ?? " "}</strong>
              <span>{figure.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The six blocks for one seller's day, in the handoff's order. */
export function SellerBlocks({
  desk,
  side,
  onSide,
  headerExtras,
}: {
  desk: HomeDesk;
  side: Side;
  onSide: (side: Side) => void;
  /** Taking new leads, and for owners the way back to the team's Home. */
  headerExtras?: ReactNode;
}) {
  const access = useSidesAccess();
  const { tasks, failed, reload, done } = useTaskList();
  // Only the type this seller works when they don't have both.
  const shown: Side =
    access && !access.inbound && access.cold
      ? "cold"
      : access && access.inbound && !access.cold
        ? "inbound"
        : side;
  const own = desk.sides?.[shown] ?? null;
  return (
    <div className={styles.me}>
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
          extras={headerExtras}
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
        />
      </div>
      <div data-area="follow">
        <UpcomingFollowUps side={shown} own={own} />
      </div>
      <div data-area="perf">
        <TodayPerformance side={shown} own={own} />
      </div>
      <div data-area="breaks">
        <LongestBreaks breaks={desk.breaks} />
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
      />
      <UpcomingFollowUps side={side} own={desk.sides?.[side] ?? null} />
    </>
  );
}
