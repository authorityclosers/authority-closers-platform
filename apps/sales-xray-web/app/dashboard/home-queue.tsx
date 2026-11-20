"use client";

/**
 * A seller's Home as the owner picked it (round 2, board 2 "Home / Today",
 * option C "Work queue + lead preview", 20 Nov 2026): Home answers one
 * question, "who do I call now?".
 *
 * - On a PC (from 1024 px): the work queue on the left, the lead picked from
 *   it in the middle, ready to call, and a slim Today column on the right with
 *   speed to lead and the day's numbers. The whole screen is used.
 * - On a phone: Next action first (with how long a new lead has waited), then
 *   the rest of the queue, each row one Call, then speed to lead and Today.
 *
 * The queue is Leads › To Call itself, in its order (GET /leads?view=to_call),
 * so Home and Leads never disagree; a new lead goes to its top with its
 * waiting time. Inbound | Cold is a small switch in the header, not a bar.
 * Only real numbers: what the server doesn't send is not shown.
 */

import {
  CalendarCheck,
  CalendarDays,
  ChevronRight,
  Clock,
  Layers,
  Phone,
  PhoneCall,
  PhoneOutgoing,
  SquareCheck,
  Timer,
  UserPlus,
} from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { displayName } from "../display-name";
import {
  ago,
  readLeads,
  type LeadPage,
  type LeadRow,
  type ListedTask,
} from "../leads/leads-client";
import { readEffort, type Effort } from "../performance/performance-client";
import { CallLens } from "../ui/call-lens/call-lens";
import { useGo } from "../calls/call-rows";
import { DashboardGreeting } from "./dashboard-greeting";
import { breakLength } from "./home-today";
import { HomeLeadHost, useHomeLead } from "./home-lead";
import { retryHome, useHomeRead } from "./home-load";
import { LeadMeta } from "./lead-meta";
import type { HomeDesk, HomeSide } from "./my-day-client";
import {
  NextCall,
  PendingAction,
  SideBlock,
  SideWait,
  useSidesAccess,
  useTaskList,
} from "./seller-home";
import { TickMark } from "./smart-home";
import { talkOrDash } from "./talk-time";
import {
  arrivedAt,
  clockDay,
  DAY,
  initials,
  KIND_WORDS,
  LONG_WAIT_MINUTES,
  noteBeside,
  queueKind,
  queueLine,
  useMinute,
  waited,
  waitingMinutes,
  type QueueKind,
} from "./queue-words";
import type { Side } from "../ui/side-selector";
import {
  handOverAnswer,
  handOverLead,
  handOverRound,
} from "../leads/lead-handoff";
import sellerStyles from "./seller-home.module.css";
import styles from "./home-queue.module.css";

/** Leads › To Call on this side, first page, in its own order. */
export function useQueue(side: Side) {
  return useHomeRead<LeadPage>(`queue:${side}`, (signal) =>
    readLeads({ scope: "mine", more: { side, view: "to_call" } }, signal),
  );
}

/** Today's figures from the Performance engine: the seller's own, and the
 *  team's when the viewer may see it (an owner on Me). One read with the
 *  team's Home (key "effort:1"). */
export function useTodayEffort() {
  return useHomeRead<Effort>("effort:1", (signal) => readEffort(1, signal));
}

/** My speed to lead today, and the team's when this read carries it. */
export function speedOf(
  effort: Effort | null,
  me: string | null,
): { mine: number | null; team: number | null } | null {
  if (!effort) return null;
  const own = effort.sellers.find((seller) => seller.person_id === me);
  const mine = (own ?? (effort.team ? null : effort.sellers[0]))?.inbound
    .first_call_minutes;
  return {
    mine: mine ?? null,
    team: effort.team ? effort.inbound.first_call_minutes : null,
  };
}

/** One row of the queue. On a PC a tap picks it into the preview; on a phone
 *  it opens the lead, and its own Call calls. */
function QueueRow({
  lead,
  now,
  picked,
  next,
  onPick,
}: {
  lead: LeadRow;
  now: Date;
  picked: boolean;
  /** The phone's Next action card shows this one: its row waits on the PC. */
  next: boolean;
  onPick: (id: string) => void;
}) {
  const name = displayName(lead.name);
  const kind = queueKind(lead, now);
  const note =
    kind === "later" ? noteBeside(lead.next_action_note, name) : null;
  const long = kind === "new" && waitingMinutes(lead, now) >= LONG_WAIT_MINUTES;
  return (
    <li
      className={styles.row}
      data-kind={kind}
      data-picked={picked || undefined}
      data-next={next || undefined}
    >
      {/* PC: picks the lead into the preview; the phone hides this. */}
      <button
        type="button"
        className={styles.pick}
        aria-pressed={picked}
        data-sx-feature="home_queue_pick"
        onClick={() => onPick(lead.lead_id)}
      >
        <span className={styles.face} aria-hidden="true">
          {initials(lead.name)}
        </span>
        <span className={styles.rowWords}>
          <strong>{name}</strong>
          <span data-warn={kind === "late" || long || undefined}>
            {queueLine(lead, now)}
            {note ? ` · ${note}` : ""}
          </span>
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </button>
      {/* Phone: the name opens the lead over Home; Call calls it there. */}
      <Link className={styles.open} href={`/leads?lead=${lead.lead_id}`}>
        <span className={styles.face} aria-hidden="true">
          {initials(lead.name)}
        </span>
        <span className={styles.rowWords}>
          <strong>{name}</strong>
          <span data-warn={kind === "late" || long || undefined}>
            {queueLine(lead, now)}
            {note ? ` · ${note}` : ""}
          </span>
        </span>
      </Link>
      <Link
        className={styles.call}
        href={`/leads?lead=${lead.lead_id}`}
        aria-label={`Call ${name}`}
        data-sx-feature="home_queue_call"
        onClick={() => handOverLead(lead.lead_id, true)}
      >
        <Phone size={18} aria-hidden="true" />
      </Link>
    </li>
  );
}

/** The queue in To Call's order, with a small heading wherever the kind of
 *  row changes (Missed calls, New leads, Late, Later today). */
export function WorkQueue({
  side,
  leads,
  total,
  state,
  picked,
  onPick,
  skip,
  tasks,
  onTask,
  now,
}: {
  side: Side;
  leads: LeadRow[];
  total: number;
  state: "loading" | "ready" | "error";
  picked: string | null;
  onPick: (id: string) => void;
  /** The phone's Next action already shows this lead. */
  skip: string | null;
  tasks: ListedTask[] | null;
  onTask: (task: ListedTask) => void;
  now: Date;
}) {
  const rows = leads.slice(0, 12);
  const groups: { kind: QueueKind; leads: LeadRow[] }[] = [];
  for (const lead of rows) {
    const kind = queueKind(lead, now);
    const last = groups[groups.length - 1];
    if (last?.kind === kind) last.leads.push(lead);
    else groups.push({ kind, leads: [lead] });
  }
  const seeAll = `/leads${side === "cold" ? "?side=cold&view=to_call" : "?view=to_call"}`;
  const open = (tasks ?? []).filter((task) => task.status !== "done");
  return (
    <section className={styles.queue} aria-labelledby="queue-title">
      <div className={styles.head}>
        <h2 id="queue-title">Work queue</h2>
        {total ? (
          <Link className={styles.more} href={seeAll}>
            {`All ${total} in Leads`}
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        ) : null}
      </div>
      {state === "loading" && !rows.length ? (
        <ul className={styles.rows} aria-busy="true">
          {[0, 1, 2].map((index) => (
            <li key={index} className={styles.wait} aria-hidden="true" />
          ))}
        </ul>
      ) : state === "error" && !rows.length ? (
        <p className={styles.quiet} role="alert">
          The queue didn&apos;t load. Pull down or come back to try again.
        </p>
      ) : !rows.length ? (
        <p className={styles.quiet}>
          {side === "cold"
            ? "No cold leads to call right now."
            : "Nobody to call right now. New leads show here as they come."}
        </p>
      ) : (
        groups.map((group, index) => (
          <div
            key={`${group.kind}-${index}`}
            className={styles.group}
            data-only={
              group.leads.every((lead) => lead.lead_id === skip) || undefined
            }
          >
            <h3 className={styles.kind} data-kind={group.kind}>
              {KIND_WORDS[group.kind]}
            </h3>
            <ul className={styles.rows}>
              {group.leads.map((lead) => (
                <QueueRow
                  key={lead.lead_id}
                  lead={lead}
                  now={now}
                  picked={lead.lead_id === picked}
                  next={lead.lead_id === skip}
                  onPick={onPick}
                />
              ))}
            </ul>
          </div>
        ))
      )}
      {open.length ? (
        <div className={styles.group}>
          <h3 className={styles.kind} data-kind="task">
            Tasks today
          </h3>
          <ul className={styles.rows}>
            {open.slice(0, 4).map((task) => (
              <li key={task.task_id} className={styles.taskRow}>
                <TickMark
                  label={`Done: ${task.title}`}
                  checked={false}
                  onChange={() => onTask(task)}
                />
                <Link
                  className={styles.taskWords}
                  href={
                    task.lead_id
                      ? `/leads?lead=${task.lead_id}`
                      : "/leads?tab=tasks"
                  }
                >
                  <strong>{task.title}</strong>
                  <span data-warn={task.overdue || undefined}>
                    {task.starts_at
                      ? `${task.overdue ? "Was due " : ""}${clockDay(task.starts_at, now)}`
                      : "Today"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.fact}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** The lead picked from the queue, ready to call (PC). */
export function LeadPreview({
  lead,
  side,
  now,
}: {
  lead: LeadRow | null;
  side: Side;
  now: Date;
}) {
  const here = useHomeLead();
  const go = useGo();
  if (!lead)
    return (
      <section className={styles.preview} aria-labelledby="preview-title">
        <h2 id="preview-title" className={styles.previewTitle}>
          Lead preview
        </h2>
        <p className={styles.quiet}>
          Pick a lead from the queue to see it here.
        </p>
      </section>
    );
  const name = displayName(lead.name);
  const first = name.split(" ")[0];
  const kind = queueKind(lead, now);
  const cold = side === "cold";
  const round = cold && kind !== "missed";
  const where = [lead.company, lead.city].filter(Boolean).join(" · ");
  const note = noteBeside(lead.next_action_note, name);
  const call = () =>
    round ? handOverRound(lead.lead_id) : handOverLead(lead.lead_id, true);
  return (
    <section
      className={styles.preview}
      aria-labelledby="preview-title"
      key={lead.lead_id}
    >
      <h2 id="preview-title" className={styles.previewTitle}>
        Lead preview
      </h2>
      <div className={styles.who}>
        <span className={styles.bigFace} aria-hidden="true">
          {initials(lead.name)}
        </span>
        <Link className={styles.name} href={`/leads?lead=${lead.lead_id}`}>
          {name}
        </Link>
        <LeadMeta
          className={styles.meta}
          source={lead.source_label}
          why={
            kind === "missed" && lead.missed_at
              ? queueLine(lead, now)
              : cold && lead.why === "New lead"
                ? "Unworked"
                : lead.why
          }
        />
        <p className={styles.came}>
          {`Came in ${clockDay(arrivedAt(lead), now)}`}
          {kind === "new" ? (
            <b
              data-warn={
                waitingMinutes(lead, now) >= LONG_WAIT_MINUTES || undefined
              }
            >
              {` · waiting ${waited(waitingMinutes(lead, now))}`}
            </b>
          ) : null}
        </p>
      </div>
      <dl className={styles.facts}>
        {lead.interest ? (
          <Fact label="Interested in">{lead.interest}</Fact>
        ) : null}
        {where ? <Fact label="Where">{where}</Fact> : null}
        {lead.next_action_at ? (
          <Fact label={kind === "late" ? "Was due" : "Planned"}>
            {clockDay(lead.next_action_at, now)}
            {note ? ` · ${note}` : ""}
          </Fact>
        ) : null}
        <Fact label="Last call">
          {lead.last_contact_at
            ? `${lead.last_result_label ?? "Called"} · ${ago(lead.last_contact_at, now)}`
            : "None yet"}
        </Fact>
        {lead.attempts ? (
          <Fact label="Tries">{String(lead.attempts)}</Fact>
        ) : null}
      </dl>
      <div className={styles.actions}>
        <CallLens
          href={leadsHrefFor(side)}
          onClick={(event) => {
            // As Next action's Call: a one-off call opens the lead here, on
            // Home, the call started; a cold round runs through Leads.
            if (here && !round) {
              event.preventDefault();
              here.lead(lead.lead_id, "call");
              return;
            }
            call();
            if (!here) go(leadsHrefFor(side));
          }}
        >
          {kind === "missed"
            ? `Call back ${first}`
            : round
              ? "Start Cold Calling"
              : `Call ${first}`}
        </CallLens>
        <Link
          className={styles.secondary}
          href={`/leads?lead=${lead.lead_id}`}
          data-sx-feature="home_preview_open"
        >
          Open lead
        </Link>
      </div>
    </section>
  );
}

const leadsHrefFor = (side: Side) =>
  side === "cold" ? "/leads?side=cold&view=to_call" : "/leads?view=to_call";

/** Speed to lead in one line: mine, and the team's when this read has it. */
function speedWords(speed: { mine: number | null; team: number | null }) {
  return speed.mine === null
    ? "No new lead called yet today"
    : `${waited(Math.round(speed.mine))}${speed.team !== null ? ` · team ${waited(Math.round(speed.team))}` : ""}`;
}

/** The phone's speed to lead strip, under the queue. */
export function SpeedStrip({
  speed,
}: {
  speed: { mine: number | null; team: number | null } | null;
}) {
  if (!speed) return null;
  return (
    <Link
      className={styles.speedStrip}
      href="/growth"
      data-sx-feature="home_speed_open"
    >
      <Timer size={18} aria-hidden="true" />
      <span>
        <b>Speed to lead</b> {speedWords(speed)}
      </span>
      <ChevronRight size={16} aria-hidden="true" />
    </Link>
  );
}

type Line = {
  key: string;
  icon: ReactNode;
  label: string;
  value: string | null;
  href: string;
  /** Opens its list in a sheet over Home (HomeLeadHost's data-card). */
  card?: boolean;
};

function LineList({ lines, label }: { lines: Line[]; label: string }) {
  return (
    <ul className={styles.lines} aria-label={label}>
      {lines.map((line) => (
        <li key={line.key}>
          <Link
            className={styles.line}
            href={line.href}
            data-card={line.card ? line.key : undefined}
            data-line={line.key}
            data-sx-feature={line.card ? "home_list_open" : "home_today_open"}
          >
            <span aria-hidden="true">{line.icon}</span>
            <span>{line.label}</span>
            <b>{line.value ?? "–"}</b>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** The slim Today column: speed to lead, the day's numbers, the lists. */
export function TodayColumn({
  side,
  own,
  other = null,
  speed,
  tasks,
  lateTasks,
}: {
  side: Side;
  own: HomeSide | null;
  /** The other side's day: with no call on this side, a line says where
   *  today's calls are (#170, #174, #175: never a bare 0 beside them). */
  other?: HomeSide | null;
  speed: { mine: number | null; team: number | null } | null;
  tasks: number | null;
  lateTasks: number | null;
}) {
  const numbers = own?.numbers;
  const calls = `/analysis/calls?day=today&side=${side}`;
  const leads = (query: Record<string, string>) => {
    const params = new URLSearchParams(query);
    if (side === "cold") params.set("side", "cold");
    return `/leads?${params}`;
  };
  const cold = side === "cold";
  const day: Line[] = [
    {
      key: "calls",
      icon: <PhoneOutgoing size={18} />,
      label: "Calls",
      value: numbers ? String(numbers.calls) : null,
      href: calls,
    },
    {
      key: "connected",
      icon: <PhoneCall size={18} />,
      label: "Connected",
      value: numbers ? String(numbers.connected) : null,
      href: `${calls}&outcome=connected`,
    },
    {
      key: "talk",
      icon: <Clock size={18} />,
      label: "Talk",
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
      key: "follow_ups_done",
      icon: <CalendarCheck size={18} />,
      label: "Follow-ups done",
      value: numbers ? String(numbers.follow_ups_done) : null,
      href: leads({ view: "follow_ups", when: "today" }),
    },
    {
      key: "given",
      icon: <UserPlus size={18} />,
      label: "New leads given to you",
      value: numbers ? String(numbers.new_assigned) : null,
      href: leads({ view: "to_call", step: own?.new_key ?? "new" }),
    },
  ];
  const lists = (
    [
      own?.new_key !== null
        ? {
            key: "new",
            icon: cold ? <PhoneOutgoing size={18} /> : <UserPlus size={18} />,
            label: cold ? "Unworked leads" : "New leads",
            value: own ? String(own.counts.new) : null,
            href: leads({ view: "to_call", step: own?.new_key ?? "new" }),
            card: true,
          }
        : null,
      own?.open_key !== null
        ? {
            key: "open",
            icon: <Layers size={18} />,
            label: "Open leads",
            value: own ? String(own.counts.open_leads) : null,
            href: leads({ view: "all", step: own?.open_key ?? "open_leads" }),
            card: true,
          }
        : null,
      {
        key: "follow_ups",
        icon: <CalendarDays size={18} />,
        label: "Follow-ups due today",
        value: own ? String(own.counts.follow_ups_today) : null,
        href: leads({ view: "follow_ups", when: "today" }),
        card: true,
      },
      {
        key: "tasks",
        icon: <SquareCheck size={18} />,
        label: lateTasks ? `Tasks · ${lateTasks} late` : "Tasks",
        value: tasks === null ? null : String(tasks),
        href: lateTasks ? "/leads?tab=tasks&tasks=overdue" : "/leads?tab=tasks",
        card: true,
      },
    ] as (Line | null)[]
  ).filter((line): line is Line => line !== null);
  return (
    <aside className={styles.today} aria-labelledby="today-col-title">
      <h2 id="today-col-title" className={styles.todayTitle}>
        Today
      </h2>
      {speed && !cold ? (
        <Link
          className={styles.speed}
          href="/growth"
          data-sx-feature="home_speed_open"
          data-empty={speed.mine === null || undefined}
        >
          <span className={styles.speedHead}>
            <Timer size={18} aria-hidden="true" />
            Speed to lead
          </span>
          {speed.mine === null ? (
            <span className={styles.speedNone}>
              No new lead called yet today
            </span>
          ) : (
            <span className={styles.speedFigures}>
              <strong>{waited(Math.round(speed.mine))}</strong>
              {speed.team !== null ? (
                <span>{`team ${waited(Math.round(speed.team))}`}</span>
              ) : null}
            </span>
          )}
          <span className={styles.speedNote}>
            Your new Inbound leads today, median to the first call
          </span>
        </Link>
      ) : null}
      <LineList
        label={`Done today · ${cold ? "Cold" : "Inbound"} calls`}
        lines={day}
      />
      {numbers && !numbers.calls && other?.numbers?.calls ? (
        <p className={styles.quiet} data-elsewhere="">
          {`${other.numbers.calls} tried on ${cold ? "Inbound" : "Cold"} today`}
        </p>
      ) : null}
      <h3 className={styles.listsTitle}>Your lists</h3>
      <LineList label="Your lists" lines={lists} />
    </aside>
  );
}

/** Home's line: the greeting and today's date, the side switch beside it
 *  (board 2: Inbound | Cold from a full-width bar to a small switch). */
export function HomeHeader({ side }: { side: ReactNode }) {
  const now = useMinute();
  return (
    <header className={styles.header}>
      <DashboardGreeting subtitle={DAY.format(now)} />
      {side ? <div className={styles.sideSwitch}>{side}</div> : null}
    </header>
  );
}

type SidesAccess = { inbound: boolean; cold: boolean };

/** A seller's Home, option C: header, a waiting answer, then the board. */
export function QueueHome({
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
  /** Which sides this seller works; null while they are on the way. */
  access?: SidesAccess | null;
  state?: "ready" | "loading" | "error";
}) {
  const fetched = useSidesAccess(given === undefined);
  const access = given === undefined ? fetched : given;
  const shown: Side =
    access && !access.inbound && access.cold
      ? "cold"
      : access && access.inbound && !access.cold
        ? "inbound"
        : side;
  const own = desk?.sides?.[shown] ?? null;
  const me = desk?.me?.person_id ?? null;
  const ready = desk !== null && state === "ready";
  const { tasks, late, overdue, done } = useTaskList(true);
  const queue = useQueue(shown);
  const effort = useTodayEffort();
  const now = useMinute();
  const [picked, setPicked] = useState<string | null>(null);
  const leads = queue.value?.leads ?? [];
  const chosen =
    leads.find((lead) => lead.lead_id === picked) ?? leads[0] ?? null;
  const today =
    tasks === null
      ? null
      : [
          ...late.filter(
            (task) => !tasks.some((item) => item.task_id === task.task_id),
          ),
          ...tasks,
        ];
  const go = useGo();
  return (
    <HomeLeadHost me={desk?.me ?? null} onChanged={retryHome}>
      <div className={styles.home} data-queue-home="" data-side={shown}>
        <HomeHeader
          side={
            access ? (
              <SideBlock
                side={shown}
                access={access}
                own={own}
                inbound={desk?.sides?.inbound ?? null}
                onSide={onSide}
              />
            ) : given === null ? (
              <SideWait side={shown} />
            ) : null
          }
        />
        {desk ? (
          <PendingAction
            calls={desk.unanswered}
            onFinish={(leadId) => {
              handOverAnswer(leadId);
              go("/leads");
            }}
          />
        ) : null}
        <div className={styles.board}>
          <div className={styles.nextCard}>
            <NextCall side={shown} own={own} state={ready ? "ready" : state} />
          </div>
          <WorkQueue
            side={shown}
            leads={leads}
            total={queue.value?.total ?? 0}
            state={queue.value ? "ready" : queue.failed ? "error" : "loading"}
            picked={chosen?.lead_id ?? null}
            onPick={setPicked}
            skip={own?.next_lead?.lead_id ?? null}
            tasks={ready ? today : null}
            onTask={done}
            now={now}
          />
          <LeadPreview lead={chosen} side={shown} now={now} />
          {shown === "inbound" ? (
            <div className={styles.phoneSpeed}>
              <SpeedStrip speed={speedOf(effort.value, me)} />
            </div>
          ) : null}
          <TodayColumn
            side={shown}
            own={ready ? own : null}
            other={
              ready
                ? (desk?.sides?.[shown === "cold" ? "inbound" : "cold"] ?? null)
                : null
            }
            speed={speedOf(effort.value, me)}
            tasks={
              ready && tasks
                ? tasks.filter((task) => task.status !== "done").length
                : null
            }
            lateTasks={ready ? overdue : null}
          />
        </div>
        {/* The page's end keeps the Call band's room on a phone. */}
        {ready && own?.next_lead ? (
          <div className={sellerStyles.bandRoom} aria-hidden="true" />
        ) : null}
      </div>
    </HomeLeadHost>
  );
}

/** Home's outline before anything is read (home-outline.tsx): the same
 *  header and board, waiting, with no reads of its own. */
export function QueueOutline({ access }: { access: SidesAccess | null }) {
  const side: Side =
    access && !access.inbound && access.cold ? "cold" : "inbound";
  return (
    <div className={styles.home} data-queue-home="" data-side={side}>
      <HomeHeader
        side={
          !access || (access.inbound && access.cold) ? (
            <SideWait side={side} />
          ) : null
        }
      />
      <div className={styles.board}>
        <div className={styles.nextCard}>
          <NextCall side={side} own={null} state="loading" />
        </div>
        <section className={styles.queue} aria-label="Work queue">
          <div className={styles.head}>
            <h2>Work queue</h2>
          </div>
          <ul className={styles.rows} aria-busy="true">
            {[0, 1, 2].map((index) => (
              <li key={index} className={styles.wait} aria-hidden="true" />
            ))}
          </ul>
        </section>
        <section className={styles.preview} aria-label="Lead preview">
          <h2 className={styles.previewTitle}>Lead preview</h2>
          <span className={styles.waitBlock} aria-hidden="true" />
        </section>
        <aside className={styles.today} aria-label="Today">
          <h2 className={styles.todayTitle}>Today</h2>
          <span className={styles.waitBlock} aria-hidden="true" />
        </aside>
      </div>
    </div>
  );
}
