"use client";

/**
 * To call (the desk): the due-now list (overdue first, then call now, then
 * later today), what's coming up and my day. Plain words only; nothing
 * internal on screen (owner, 16 Oct).
 *
 * Owner, 22 Oct 2026: no big green card, no wide switches, no big "All
 * clear" panel and no list of links at the bottom. The page's stage tabs
 * carry the counts, Start calling sits in the bar above the tab bar, an
 * empty list is one line with one action, and Leads' settings live in its
 * ⋯ menu. Rows still swipe right to call and left to WhatsApp (now with the
 * apps' own marks), and a long hold opens quick actions.
 */

import { Hand, Inbox, Mail, Phone, X, type LucideIcon } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { ChannelMark } from "../chats/channel-mark";
import { Avatar, Badge, Button, Kpi, Panel, Tiles, type Tone } from "../ui/kit";
import { useRowKeys } from "../ui/row-keys";
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

/**
 * Leads to call now, each once: those who called and weren't reached (Call back), and
 * those due now. The To call tab and the app's badge say this one number (Redmi, 23 Oct
 * 2026: the tab said 0 over a Call back row; the server's badge counts the same).
 */
export function toCallNow(desk: Pick<Desk, "queue" | "call_back">): number {
  const leads = new Set((desk.call_back ?? []).map((row) => row.lead_id));
  for (const row of desk.queue)
    if (row.overdue || !["later", "open", "closed"].includes(row.why_kind))
      leads.add(row.lead_id);
  return leads.size;
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
  /** L on a computer: the lead opens on "How did the call go?". */
  onLog?: (row: LeadRow) => void;
  onMessage?: (row: LeadRow) => void;
  onHold?: (row: LeadRow) => void;
  /** The card's own buttons: one tap to call, WhatsApp or email (owner, 24 Oct 2026). */
  onTap?: (row: LeadRow, channel: QuickChannel) => void;
};

export type QuickChannel = "call" | "whatsapp" | "email";

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
  const tap = actions?.onTap;
  const tags = (
    <>
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
    </>
  );
  return (
    <li
      ref={rowRef}
      className={styles.leadLine}
      data-lead-row=""
      data-row-key={row.lead_id}
      data-overdue={row.overdue || undefined}
      {...bind}
    >
      {reachable && actions ? (
        // Owner, 22 Oct: the swipes show what they do, with the apps' marks.
        <span className={styles.swipeBack} aria-hidden="true">
          <span data-side="right">
            <span className={styles.swipeIcon}>
              <Phone size={18} />
            </span>
            Call
          </span>
          <span data-side="left">
            <span className={styles.swipeIcon}>
              <ChannelMark channel="whatsapp" size={22} />
            </span>
            WhatsApp
          </span>
        </span>
      ) : null}
      <div
        ref={face}
        className={styles.leadFace}
        data-quick={tap ? "" : undefined}
      >
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
                row.missed_at
                  ? "bad"
                  : row.overdue
                    ? "warn"
                    : WHY_TONE[row.why_kind]
              }
            >
              {row.overdue ? <b className={styles.lateTag}>Late</b> : null}
              {whyLine(row)}
            </span>
          </span>
          {tap ? null : <span className={styles.leadEnd}>{tags}</span>}
        </button>
        {tap ? (
          // Beside the card's tap area, never inside it: the stage above the
          // buttons on a phone. A lead with no number shows them greyed, with why.
          <span className={styles.leadEnd} data-quick="">
            <span className={styles.leadTags}>{tags}</span>
            <span className={styles.leadQuick}>
              <button
                type="button"
                className={styles.quickAct}
                data-channel="call"
                aria-label={
                  reachable
                    ? `Call ${row.name}`
                    : `No number to call ${row.name}`
                }
                disabled={!reachable}
                onClick={() => tap(row, "call")}
              >
                <Phone size={16} aria-hidden="true" />
              </button>
              <button
                type="button"
                className={styles.quickAct}
                data-channel="whatsapp"
                aria-label={
                  reachable
                    ? `WhatsApp ${row.name}`
                    : `No number to WhatsApp ${row.name}`
                }
                disabled={!reachable}
                onClick={() => tap(row, "whatsapp")}
              >
                <ChannelMark channel="whatsapp" size={18} />
              </button>
              {row.has_email ? (
                <button
                  type="button"
                  className={styles.quickAct}
                  data-channel="email"
                  aria-label={`Email ${row.name}`}
                  onClick={() => tap(row, "email")}
                >
                  <Mail size={16} aria-hidden="true" />
                </button>
              ) : null}
            </span>
          </span>
        ) : null}
      </div>
    </li>
  );
}

/** An empty list in one line: what goes here, and at most one way to start. */
export function InlineEmpty({
  icon: Icon,
  title,
  text,
  action,
}: {
  icon: LucideIcon;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className={styles.inlineEmpty} role="status">
      <span className={styles.inlineEmptyIcon} aria-hidden="true">
        <Icon size={18} />
      </span>
      <span className={styles.inlineEmptyWords}>
        <strong>{title}</strong>
        <small>{text}</small>
      </span>
      {action}
    </div>
  );
}

const HINT_KEY = "sx-leads-swipe-hint";

/** Once, above the list: what a swipe does (owner, 22 Oct: "need icons"). */
function SwipeHint() {
  const [shown, setShown] = useState(() => {
    try {
      return localStorage.getItem(HINT_KEY) !== "seen";
    } catch {
      return true;
    }
  });
  if (!shown) return null;
  return (
    <p className={styles.swipeHint}>
      <Hand size={15} aria-hidden="true" />
      <span>
        Swipe a lead right to <Phone size={13} aria-label="call" /> call, left
        to <ChannelMark channel="whatsapp" size={14} labelled /> WhatsApp. Hold
        it for more.
      </span>
      <button
        type="button"
        className={styles.swipeHintClose}
        aria-label="Got it"
        onClick={() => {
          try {
            localStorage.setItem(HINT_KEY, "seen");
          } catch {
            // Storage blocked: hidden for this visit only.
          }
          setShown(false);
        }}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </p>
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
  const sections = deskSections(desk.queue, desk.call_back ?? []);
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

export function DeskView({
  desk,
  onOpen,
  onAdd,
  actions,
  afterHero,
}: {
  desk: Desk;
  onOpen: (leadId: string) => void;
  /** The empty list's one action: add a lead. */
  onAdd: () => void;
  actions: RowActions;
  /** One-time offers above the list (the app banner, alerts, call logging). */
  afterHero?: ReactNode;
}) {
  const { counts, numbers } = desk;
  const upcoming = desk.upcoming ?? [];
  const callBack = desk.call_back ?? [];
  const next = upcoming[0];
  const lists = useRef<HTMLDivElement>(null);
  const byId = (id: string) =>
    [...callBack, ...desk.queue, ...upcoming].find((row) => row.lead_id === id);
  useRowKeys(lists, {
    open: onOpen,
    call: (id) => {
      const row = byId(id);
      if (row?.phone_last4) actions.onCall?.(row);
    },
    log: (id) => {
      const row = byId(id);
      if (row) actions.onLog?.(row);
    },
  });
  return (
    <>
      <div className={styles.compactStack}>{afterHero}</div>
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
        <div className={styles.deskMain} ref={lists}>
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
          {desk.queue.length ? (
            <Panel
              title="Today"
              sub={`${desk.queue.length}`}
              tools={
                counts.overdue ? (
                  <Badge tone="bad">{`${counts.overdue} late`}</Badge>
                ) : undefined
              }
            >
              <SwipeHint />
              <Sections desk={desk} onOpen={onOpen} actions={actions} />
            </Panel>
          ) : (
            <InlineEmpty
              icon={Inbox}
              title={counts.open ? "All caught up" : "No leads yet"}
              text={
                next?.next_action_at
                  ? `Next call ${when(next.next_action_at)}: ${next.name}.`
                  : counts.open
                    ? "Your follow-ups are later. New leads land here first."
                    : "New leads land here the moment they come in."
              }
              action={
                <Button onClick={onAdd} className={styles.inlineEmptyAction}>
                  Add lead
                </Button>
              }
            />
          )}
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
        </aside>
      </div>
    </>
  );
}
