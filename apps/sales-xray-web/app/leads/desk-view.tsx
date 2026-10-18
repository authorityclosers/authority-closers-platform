"use client";

/**
 * My desk: one big "who to call now" card, the counts, the due-now list
 * (overdue first, then call now, then later today), what's coming up and my
 * day. Plain words only; nothing internal on screen (owner, 16 Oct).
 *
 * Phones (UX study, 17 Oct): Start calling is the first thing on screen, the
 * counts are one compact strip, rows swipe right to call and left to message,
 * a long hold opens quick actions, and the other tabs sit at the bottom.
 */

import {
  ChevronRight,
  Inbox,
  MessageCircle,
  Phone,
  PhoneCall,
  Plus,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  Avatar,
  Badge,
  Button,
  Empty,
  Kpi,
  Panel,
  Tiles,
  type Tone,
} from "../ui/kit";
import { useRowGestures } from "./gestures";
import {
  ago,
  deskSections,
  minutesLabel,
  when,
  type Desk,
  type LeadRow,
} from "./leads-client";
import styles from "./leads.module.css";

const WHY_TONE: Record<LeadRow["why_kind"], Tone> = {
  due: "warn",
  new: "accent",
  retry: "neutral",
  later: "neutral",
  open: "neutral",
  closed: "good",
  waiting: "bad",
};

/** "Why now" plus the time that makes it urgent, in the seller's own clock. */
export function whyLine(row: LeadRow, now: Date = new Date()): string {
  if (row.missed_at)
    return `Missed call ${ago(row.missed_at, now)}${
      (row.missed_calls ?? 0) > 1 ? ` · ${row.missed_calls} calls` : ""
    } · call back`;
  if (row.why_kind === "new") return `${row.why} · ${ago(row.created_at, now)}`;
  if (
    row.next_action_at &&
    (row.why_kind === "due" || row.why_kind === "retry")
  )
    return `${row.why} · was ${when(row.next_action_at, now)}`;
  if (
    row.next_action_at &&
    (row.why_kind === "later" || row.why_kind === "open")
  )
    return `${row.why} · ${when(row.next_action_at, now)}`;
  return row.why;
}

/** How many calls are due right now: late ones, new leads and retries due. */
export function dueNow(desk: Pick<Desk, "queue">): number {
  return desk.queue.filter(
    (row) => row.overdue || !["later", "open", "closed"].includes(row.why_kind),
  ).length;
}

/** Where the lead came from, as a seller would say it. */
export function sourceText(
  row: Pick<LeadRow, "source" | "source_label">,
): string {
  if (row.source === "synthetic") {
    const kind = row.source_label.split("·").pop()?.trim() ?? "";
    return kind ? kind[0].toUpperCase() + kind.slice(1) : "Lead";
  }
  if (row.source === "csv") return "File upload";
  return row.source_label.replace(/^Sheet: /, "Sheet · ");
}

/** What a list row can do beyond opening: swipe and hold (fingers only). */
export type RowActions = {
  onCall?: (row: LeadRow) => void;
  onMessage?: (row: LeadRow) => void;
  onHold?: (row: LeadRow) => void;
};

export function LeadLine({
  row,
  onOpen,
  showOwner = false,
  actions,
}: {
  row: LeadRow;
  onOpen: (leadId: string) => void;
  showOwner?: boolean;
  actions?: RowActions;
}) {
  const reachable = !!row.phone_last4;
  const {
    row: rowRef,
    face,
    bind,
  } = useRowGestures({
    onSwipeRight:
      reachable && actions?.onCall ? () => actions.onCall?.(row) : undefined,
    onSwipeLeft:
      reachable && actions?.onMessage
        ? () => actions.onMessage?.(row)
        : undefined,
    onHold: actions?.onHold ? () => actions.onHold?.(row) : undefined,
  });
  const sub = [row.interest, row.company, row.city].filter(Boolean).join(" · ");
  return (
    <li
      ref={rowRef}
      className={styles.leadLine}
      data-lead-row=""
      data-overdue={row.overdue || undefined}
      {...bind}
    >
      {reachable && actions ? (
        <span className={styles.swipeBack} aria-hidden="true">
          <span data-side="right">
            <Phone size={18} />
            Call
          </span>
          <span data-side="left">
            WhatsApp
            <MessageCircle size={18} />
          </span>
        </span>
      ) : null}
      <div ref={face} className={styles.leadFace}>
        <button
          type="button"
          className={styles.leadButton}
          onClick={() => onOpen(row.lead_id)}
          aria-label={`Open ${row.name}`}
        >
          <Avatar name={row.name} size={34} />
          <span className={styles.leadMain}>
            <span className={styles.leadName}>{row.name}</span>
            {sub ? <span className={styles.leadSub}>{sub}</span> : null}
            <span
              className={styles.leadWhy}
              data-tone={
                row.overdue || row.missed_at ? "bad" : WHY_TONE[row.why_kind]
              }
            >
              {row.overdue ? <b className={styles.lateTag}>Late</b> : null}
              {whyLine(row)}
            </span>
          </span>
          <span className={styles.leadEnd}>
            <Badge
              tone={
                row.stage === "won"
                  ? "good"
                  : row.stage === "lost"
                    ? "bad"
                    : "neutral"
              }
            >
              {row.stage_label}
            </Badge>
            <span className={styles.leadOwner}>
              {showOwner ? (row.owner_name ?? "No owner yet") : sourceText(row)}
            </span>
          </span>
          <ChevronRight
            size={16}
            className={styles.leadChevron}
            aria-hidden="true"
          />
        </button>
      </div>
    </li>
  );
}

function NextUp({
  desk,
  onStart,
  onAdd,
}: {
  desk: Desk;
  onStart: () => void;
  onAdd: () => void;
}) {
  const next = desk.queue[0];
  const toCall = dueNow(desk);
  if (!next)
    return (
      <section className={styles.hero} aria-label="Next call">
        <div className={styles.heroText}>
          <span className={styles.heroEyebrow}>All clear</span>
          <h2 className={styles.heroTitle}>Nobody to call right now</h2>
          <p className={styles.heroSub}>
            New leads land here the moment they come in. Add one yourself any
            time.
          </p>
        </div>
        <Button onClick={onAdd}>
          <Plus size={16} aria-hidden="true" />
          Add a lead
        </Button>
      </section>
    );
  return (
    <section className={styles.hero} aria-label="Next call">
      <div className={styles.heroText}>
        <span className={styles.heroEyebrow}>
          {toCall
            ? `${toCall} lead${toCall === 1 ? "" : "s"} to call now`
            : "Next on your list"}
        </span>
        <h2 className={styles.heroTitle}>{next.name}</h2>
        <p className={styles.heroSub}>{whyLine(next)}</p>
      </div>
      <button type="button" className={styles.heroButton} onClick={onStart}>
        <PhoneCall size={20} aria-hidden="true" />
        Start calling
      </button>
    </section>
  );
}

/** Phones: the counts as one row of small tappable numbers. */
function CountStrip({ desk }: { desk: Desk }) {
  const { counts } = desk;
  const items: { label: string; value: number; href: string; tone?: Tone }[] = [
    ...(counts.overdue
      ? [
          {
            label: "Late",
            value: counts.overdue,
            href: "/leads?tab=all&stage=open",
            tone: "bad" as Tone,
          },
        ]
      : []),
    {
      label: "New",
      value: counts.new,
      href: "/leads?tab=all&stage=new",
      tone: "accent",
    },
    {
      label: "Due",
      value: counts.follow_up_due,
      href: "/leads?tab=all&stage=follow_up",
      tone: "warn",
    },
    {
      label: "Retry",
      value: counts.not_connected,
      href: "/leads?tab=all&stage=not_connected",
    },
    {
      label: "Later",
      value: counts.later_today,
      href: "/leads?tab=all&stage=open",
    },
  ];
  return (
    <nav className={styles.countStrip} aria-label="My leads">
      {items.map((item) => (
        <Link
          key={item.label}
          href={item.href}
          className={styles.countItem}
          data-tone={item.tone}
          prefetch={false}
        >
          <strong>{item.value}</strong>
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

function Sections({
  desk,
  onOpen,
  actions,
}: {
  desk: Desk;
  onOpen: (leadId: string) => void;
  actions: RowActions;
}) {
  const sections = deskSections(desk.queue);
  return (
    <div className={styles.sections}>
      {sections.map((section) => (
        <section
          key={section.key}
          className={styles.dueSection}
          data-section={section.key}
          aria-label={section.title}
        >
          <h3 className={styles.sectionTitle}>
            {section.title}
            <small>{section.rows.length}</small>
          </h3>
          <ul className={styles.leadList} aria-label={section.title}>
            {section.rows.map((row) => (
              <LeadLine
                key={row.lead_id}
                row={row}
                onOpen={onOpen}
                actions={actions}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export type DeskLink = {
  key: string;
  label: string;
  note?: string;
  href?: string;
  onClick?: () => void;
};

export function DeskView({
  desk,
  onOpen,
  onStart,
  onAdd,
  actions,
  afterHero,
  links,
}: {
  desk: Desk;
  onOpen: (leadId: string) => void;
  onStart: () => void;
  onAdd: () => void;
  actions: RowActions;
  /** Shown right under the next-call card (the app banner, the alerts card). */
  afterHero?: ReactNode;
  /** Phones: the other tabs and tools, listed at the bottom of the desk. */
  links: DeskLink[];
}) {
  const { counts, numbers } = desk;
  const upcoming = desk.upcoming ?? [];
  const callBack = desk.call_back ?? [];
  return (
    <>
      <NextUp desk={desk} onStart={onStart} onAdd={onAdd} />
      {afterHero}
      <CountStrip desk={desk} />
      <div className={styles.wideOnly}>
        <Tiles label="My leads">
          <Kpi
            label="New"
            tone="accent"
            value={counts.new}
            note="Not called yet"
            href="/leads?tab=all&stage=new"
          />
          <Kpi
            label="Follow-ups due"
            tone="warn"
            value={counts.follow_up_due}
            note="Due now"
            href="/leads?tab=all&stage=follow_up"
          />
          <Kpi
            label="Not connected"
            value={counts.not_connected}
            note="Try again"
            href="/leads?tab=all&stage=not_connected"
          />
          <Kpi
            label="Later today"
            value={counts.later_today}
            note={`${counts.open} open in all`}
            href="/leads?tab=all&stage=open"
          />
        </Tiles>
      </div>
      <div className={styles.deskGrid}>
        <div className={styles.deskMain}>
          {callBack.length ? (
            <Panel title="Call back" sub={`${callBack.length}`}>
              <ul className={styles.leadList} aria-label="Call back">
                {callBack.map((row) => (
                  <LeadLine
                    key={row.lead_id}
                    row={row}
                    onOpen={onOpen}
                    actions={actions}
                  />
                ))}
              </ul>
            </Panel>
          ) : null}
          <Panel
            title="Today"
            sub={desk.queue.length ? `${desk.queue.length}` : undefined}
            tools={
              <span className={styles.panelBadges}>
                {counts.overdue ? (
                  <Badge tone="bad">{`${counts.overdue} late`}</Badge>
                ) : null}
                <button
                  type="button"
                  className={styles.addSmall}
                  onClick={onAdd}
                  aria-label="Add leads"
                >
                  <Plus size={16} aria-hidden="true" />
                  <span>Add</span>
                </button>
              </span>
            }
          >
            {desk.queue.length ? (
              <Sections desk={desk} onOpen={onOpen} actions={actions} />
            ) : (
              <div className={styles.emptyQueue}>
                <Empty
                  icon={Inbox}
                  title={counts.open ? "All caught up" : "No leads yet"}
                  text={
                    counts.open
                      ? "Your follow-ups are later. New leads appear here first."
                      : "New leads appear here first."
                  }
                />
              </div>
            )}
          </Panel>
          {upcoming.length ? (
            <Panel title="Coming up" sub={`${upcoming.length}`}>
              <ul className={styles.leadList} aria-label="Coming up">
                {upcoming.map((row) => (
                  <LeadLine
                    key={row.lead_id}
                    row={row}
                    onOpen={onOpen}
                    actions={actions}
                  />
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
        <aside className={styles.deskSide} aria-label="My day">
          <Panel title="My day">
            <dl className={styles.dayNumbers}>
              <div>
                <dt>Calls</dt>
                <dd>{numbers.calls}</dd>
              </div>
              <div>
                <dt>Connected</dt>
                <dd>
                  {numbers.connected}
                  {numbers.calls ? (
                    <small>
                      {Math.round((numbers.connected / numbers.calls) * 100)}%
                    </small>
                  ) : null}
                </dd>
              </div>
              <div>
                <dt>Talk time</dt>
                <dd>{minutesLabel(numbers.talk_seconds)}</dd>
              </div>
              <div>
                <dt>Follow-ups done</dt>
                <dd>{numbers.follow_ups_done}</dd>
              </div>
            </dl>
          </Panel>
          {desk.me.can_manage && counts.unassigned ? (
            <Panel
              title="Team"
              action={{ href: "/leads?tab=team", label: "Open" }}
            >
              <p className={styles.sideNote}>
                {`${counts.unassigned} lead${counts.unassigned === 1 ? " needs" : "s need"} an owner.`}
              </p>
            </Panel>
          ) : null}
        </aside>
      </div>
      {links.length ? (
        <nav className={styles.deskLinks} aria-label="More in Leads">
          {links.map((link) =>
            link.href ? (
              <Link
                key={link.key}
                href={link.href}
                className={styles.deskLink}
                prefetch={false}
              >
                <span>{link.label}</span>
                {link.note ? <small>{link.note}</small> : null}
                <ChevronRight size={16} aria-hidden="true" />
              </Link>
            ) : (
              <button
                key={link.key}
                type="button"
                className={styles.deskLink}
                onClick={link.onClick}
              >
                <span>{link.label}</span>
                {link.note ? <small>{link.note}</small> : null}
                <ChevronRight size={16} aria-hidden="true" />
              </button>
            ),
          )}
        </nav>
      ) : null}
    </>
  );
}
