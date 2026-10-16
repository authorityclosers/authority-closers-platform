"use client";

/**
 * My desk: one big "who to call now" card, the four counts, today's queue and
 * my day. Plain words only; nothing internal on screen (owner, 16 Oct).
 */

import { ChevronRight, Inbox, PhoneCall, Plus } from "lucide-react";

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

export function LeadLine({
  row,
  onOpen,
  showOwner = false,
}: {
  row: LeadRow;
  onOpen: (leadId: string) => void;
  showOwner?: boolean;
}) {
  const sub = [row.interest, row.company, row.city].filter(Boolean).join(" · ");
  return (
    <li className={styles.leadLine}>
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
  const toCall =
    desk.counts.new + desk.counts.follow_up_due + desk.counts.not_connected;
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

export function DeskView({
  desk,
  onOpen,
  onStart,
  onAdd,
}: {
  desk: Desk;
  onOpen: (leadId: string) => void;
  onStart: () => void;
  onAdd: () => void;
}) {
  const { counts, numbers } = desk;
  return (
    <>
      <NextUp desk={desk} onStart={onStart} onAdd={onAdd} />
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
      <div className={styles.deskGrid}>
        <div className={styles.deskMain}>
          <Panel
            title="Today's list"
            sub={desk.queue.length ? `${desk.queue.length}` : undefined}
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
    </>
  );
}
