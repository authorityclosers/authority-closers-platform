"use client";

import { ChevronRight, Inbox, PhoneCall, Plus, Upload } from "lucide-react";

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
import {
  ago,
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
  if (row.why_kind === "new") return `${row.why} · ${ago(row.created_at, now)}`;
  if (
    row.next_action_at &&
    (row.why_kind === "due" || row.why_kind === "retry")
  )
    return `${row.why} · was ${when(row.next_action_at, now)}`;
  if (row.next_action_at && row.why_kind === "later")
    return `${row.why} · ${when(row.next_action_at, now)}`;
  return row.why;
}

export function LeadLine({
  row,
  onOpen,
  showOwner = false,
}: {
  row: LeadRow;
  onOpen: (leadId: string) => void;
  showOwner?: boolean;
}) {
  const sub = [row.interest, row.company, row.city, row.language]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className={styles.leadLine}>
      <button
        type="button"
        className={styles.leadButton}
        onClick={() => onOpen(row.lead_id)}
        aria-label={`Open ${row.name}`}
      >
        <Avatar name={row.name} size={32} />
        <span className={styles.leadMain}>
          <span className={styles.leadName}>
            {row.name}
            {row.test_data ? <Badge>Test</Badge> : null}
          </span>
          {sub ? <span className={styles.leadSub}>{sub}</span> : null}
          <span className={styles.leadWhy} data-tone={WHY_TONE[row.why_kind]}>
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
          {showOwner ? (
            <span className={styles.leadOwner}>
              {row.owner_name ?? "No owner yet"}
            </span>
          ) : (
            <span className={styles.leadOwner}>{row.source_label}</span>
          )}
        </span>
        <ChevronRight
          size={16}
          className={styles.leadChevron}
          aria-hidden="true"
        />
      </button>
    </li>
  );
}

export function DeskView({
  desk,
  onOpen,
  onStart,
  onAdd,
  onImport,
}: {
  desk: Desk;
  onOpen: (leadId: string) => void;
  onStart: () => void;
  onAdd: () => void;
  onImport: () => void;
}) {
  const { counts, numbers } = desk;
  return (
    <>
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
          note="Due now or overdue"
          href="/leads?tab=all&stage=follow_up"
        />
        <Kpi
          label="Not connected"
          value={counts.not_connected}
          note="Waiting for a retry"
          href="/leads?tab=all&stage=not_connected"
        />
        <Kpi
          label="Later today"
          value={counts.later_today}
          note={`${counts.open} open in all`}
          href="/leads?tab=all&stage=open"
        />
      </Tiles>
      <div className={styles.deskGrid}>
        <div className={styles.deskMain}>
          <Panel
            title="Today's queue"
            sub={desk.queue.length ? `${desk.queue.length}` : undefined}
            tools={
              desk.queue.length ? (
                <Button variant="ghost" onClick={onStart}>
                  <PhoneCall size={14} aria-hidden="true" />
                  Call them in order
                </Button>
              ) : null
            }
          >
            {desk.queue.length ? (
              <ul className={styles.leadList} aria-label="Today's queue">
                {desk.queue.map((row) => (
                  <LeadLine key={row.lead_id} row={row} onOpen={onOpen} />
                ))}
              </ul>
            ) : (
              <div className={styles.emptyQueue}>
                <Empty
                  icon={Inbox}
                  title={
                    counts.open
                      ? "Nothing due right now"
                      : "No leads on your desk yet"
                  }
                  text={
                    counts.open
                      ? "Your follow-ups are all later. New leads land here the moment they're given to you."
                      : "Add a lead, import a file, or connect a source. New leads go to whoever fits best and has the fewest open."
                  }
                />
                <div className={styles.emptyActions}>
                  <Button onClick={onAdd}>
                    <Plus size={14} aria-hidden="true" />
                    Add lead
                  </Button>
                  <Button onClick={onImport}>
                    <Upload size={14} aria-hidden="true" />
                    Import a file
                  </Button>
                </div>
              </div>
            )}
          </Panel>
        </div>
        <aside className={styles.deskSide} aria-label="My day">
          <Panel title="My day" sub="since midnight">
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
              <div>
                <dt>New for me today</dt>
                <dd>{numbers.new_assigned}</dd>
              </div>
            </dl>
          </Panel>
          {desk.me.can_manage ? (
            <Panel
              title="Team"
              action={{ href: "/leads?tab=team", label: "Open team" }}
            >
              <p className={styles.sideNote}>
                {counts.unassigned
                  ? `${counts.unassigned} lead${counts.unassigned === 1 ? " is" : "s are"} waiting for an owner.`
                  : "Every open lead has an owner."}
              </p>
            </Panel>
          ) : null}
        </aside>
      </div>
    </>
  );
}
