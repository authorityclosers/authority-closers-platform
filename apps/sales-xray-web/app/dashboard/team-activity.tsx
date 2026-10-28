"use client";

/**
 * Team activity (owner, 27 Oct 2026, of the Team view: "ugly"; orchestrator:
 * a team Recent activity feed, who called whom, reports ready, leads assigned
 * or moved, with what needs you first and the charts after). Today's work
 * across the team, newest first: each line names the lead or call, says who
 * did what in the lead's own history words, and opens the lead or the Report.
 * Reports come from the saved calls Home already reads; the rest from the
 * team's lead history (GET /v1/lead-desk/activity?team=1, owners and admins).
 */

import {
  ArrowRightLeft,
  ChevronRight,
  Clock,
  FileCheck2,
  MessageCircle,
  NotebookPen,
  Phone,
  PhoneMissed,
  Play,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { callHref, type LibrarySubmission } from "../acquisition-client";
import { callTitle } from "../call-label";
import { useGo } from "../calls/call-rows";
import { CallRowsSkeleton } from "../calls/phone-calls";
import { displayName } from "../display-name";
import { eventText } from "../leads/lead-sheet";
import { handOverLead } from "../leads/lead-handoff";
import { clockTime } from "../leads/phone-call-text";
import {
  deskRequest,
  type ActivityItem,
  type ActivityPage,
} from "../leads/leads-client";
import { notify } from "../notice-center";
import { Avatar } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import styles from "./home-v2.module.css";
import homeStyles from "./sales-home.module.css";
import timeline from "./team-activity.module.css";

/** Home's short preview; the rest is one tap away (All activity). */
export const TEAM_ROWS = 5;

/** Today's work by everyone in the workspace (owners and admins). */
export function readTeamActivity(signal?: AbortSignal) {
  return deskRequest<ActivityPage>("/activity?day=today&team=1", { signal });
}

export type TeamRow = {
  key: string;
  at: string;
  /** The line's subject, for the avatar; null when nobody did it (a lead came in). */
  actor: string | null;
  /** Who did what, subject first: "Meera called Asha Fictional · 3:34". */
  title: string;
  /** A little more: the stage, the source, who gave it. */
  line: string;
  kind: string;
  report: string | null;
  leadId: string | null;
  recording?: string | null;
};

const firstName = (name: string) => displayName(name).split(" ")[0];

/**
 * The event as a sentence that starts with who did it (orchestrator for the
 * owner, 27 Oct 2026: with the seller's face beside the lead's name in bold,
 * it read as if the lead had done it).
 */
export function teamSentence(item: ActivityItem): {
  subject: string | null;
  title: string;
  line: string;
} {
  const event = item.event;
  const lead = displayName(item.lead_name);
  const actor = event.actor_name ? firstName(event.actor_name) : null;
  const who = actor ?? "Someone";
  const talk = event.duration_seconds ? clockTime(event.duration_seconds) : "";
  switch (event.kind) {
    case "call":
      if (event.direction === "incoming")
        return {
          subject: event.actor_name,
          title: `${lead} called ${who}${talk ? ` · ${talk}` : ""}`,
          line: "From the phone's call log",
        };
      if (event.direction === "missed" || event.direction === "rejected")
        return {
          subject: event.actor_name,
          title: `${who} missed a call from ${lead}`,
          line: "Call them back",
        };
      return {
        subject: event.actor_name,
        title: `${who} called ${lead}${talk ? ` · ${talk}` : event.via === "phone" ? " · no answer" : ""}`,
        line: event.submission_id ? "Recorded" : (item.stage_label ?? ""),
      };
    case "assigned":
    case "reassigned": {
      const to = event.owner_name ? firstName(event.owner_name) : "Nobody";
      return {
        subject: event.owner_name,
        title: `${to} got ${lead}`,
        line:
          event.kind === "reassigned" && event.previous_owner_name
            ? `From ${displayName(event.previous_owner_name)}`
            : actor
              ? `Given by ${displayName(event.actor_name ?? "")}`
              : "By the lead rules",
      };
    }
    case "captured":
      return {
        subject: null,
        title: `New lead: ${lead}`,
        line: event.source_label ? `From ${event.source_label}` : "",
      };
    case "stage":
      return {
        subject: event.actor_name,
        title: `${who} moved ${lead} to ${event.stage_label ?? "a new stage"}`,
        line: event.from_label ? `Was ${event.from_label}` : "",
      };
    case "result":
      return {
        subject: event.actor_name,
        title: `${who} talked to ${lead}`,
        line: event.reason_label ?? event.stage_label ?? "",
      };
    case "note":
      return {
        subject: event.actor_name,
        title: `${who} added a note on ${lead}`,
        line: event.note ?? "",
      };
    case "scheduled":
      return {
        subject: event.actor_name,
        title: `${who} set a follow-up for ${lead}`,
        line: event.next_action_at
          ? new Date(event.next_action_at).toLocaleString(undefined, {
              day: "numeric",
              month: "short",
              hour: "numeric",
              minute: "2-digit",
            })
          : "",
      };
    case "task":
      return {
        subject: event.actor_name,
        title: `${who} ${event.task_action === "done" ? "completed" : "updated"} a follow-up for ${lead}`,
        line: event.note ?? "",
      };
    case "message":
      return {
        subject: event.actor_name,
        title: `${who} sent ${lead} ${event.channel === "SMS" ? "an SMS" : "a WhatsApp"}`,
        line: event.template_label ?? "",
      };
    default:
      return {
        subject: event.actor_name,
        title: `${lead}: ${eventText(event).title}`,
        line: item.stage_label ?? "",
      };
  }
}

export function rowFromWork(item: ActivityItem): TeamRow {
  const missed =
    item.event.direction === "missed" || item.event.direction === "rejected";
  const said = teamSentence(item);
  return {
    key: item.event_id,
    at: item.event.at,
    actor: said.subject,
    title: said.title,
    line: said.line,
    kind: missed ? "missed" : item.event.kind,
    report:
      item.event.kind === "call" ? (item.event.submission_id ?? null) : null,
    leadId: item.lead_id,
    recording: item.event.recording ? item.event.submission_id : null,
  };
}

/** A saved call whose Report is ready, as a team line. */
export function rowFromReport(call: {
  id: string;
  createdAt: string;
  label: LibrarySubmission["label"] | string;
  owner?: { name: string | null } | null;
  lead?: { name: string; leadId: string } | null;
}): TeamRow {
  const owner = call.owner?.name ?? null;
  const name = call.lead
    ? displayName(call.lead.name)
    : typeof call.label === "string"
      ? call.label
      : callTitle(call.label, "Saved call");
  return {
    key: `report-${call.id}`,
    at: call.createdAt,
    actor: owner,
    title: `Report ready: ${name}`,
    line: owner ? `${displayName(owner)}'s call` : "",
    kind: "report",
    report: call.id,
    leadId: call.lead?.leadId ?? null,
  };
}

/** Today's lines, newest first; a call already listed with its Report shows once. */
export function teamRows(
  work: readonly ActivityItem[],
  saved: readonly LibrarySubmission[],
  now: Date = new Date(),
): TeamRow[] {
  const today = now.toDateString();
  const lines = work.map(rowFromWork);
  const listed = new Set(lines.map((row) => row.report).filter(Boolean));
  const reports = saved
    .filter(
      (call) =>
        call.hasReport &&
        !listed.has(call.id) &&
        new Date(call.createdAt).toDateString() === today,
    )
    .map(rowFromReport);
  return [...lines, ...reports].sort(
    (a, b) => Date.parse(b.at) - Date.parse(a.at),
  );
}

const ICONS: Record<string, LucideIcon> = {
  call: Phone,
  missed: PhoneMissed,
  result: Phone,
  note: NotebookPen,
  stage: ArrowRightLeft,
  message: MessageCircle,
  assigned: UserPlus,
  reassigned: UserPlus,
  captured: Sparkles,
  report: FileCheck2,
};

type Work =
  | { status: "loading" }
  | { status: "ready"; items: ActivityItem[] }
  | { status: "off" };

/** "10 am": the hour a group of lines happened in, this phone's time. */
const hourWords = (at: Date) => {
  const hour = at.getHours() % 12 || 12;
  return `${hour}\u00a0${at.getHours() < 12 ? "am" : "pm"}`;
};

/** "10:42": a line's time of day; its hour heads the group. */
const timeOfDay = (at: Date) =>
  `${at.getHours() % 12 || 12}:${String(at.getMinutes()).padStart(2, "0")}`;

export type HourGroup = { key: string; hour: string; rows: TeamRow[] };

/** Lines grouped by the hour they happened in, newest first (owner Home v3, C). */
export function byHour(
  rows: readonly TeamRow[],
  timeZone?: string,
): HourGroup[] {
  const groups: HourGroup[] = [];
  for (const row of rows) {
    const at = new Date(row.at);
    const key = timeZone
      ? new Intl.DateTimeFormat("en-GB", {
          timeZone,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "numeric",
        }).format(at)
      : `${at.toDateString()}-${at.getHours()}`;
    const last = groups[groups.length - 1];
    if (last?.key === key) last.rows.push(row);
    else groups.push({ key, hour: hourWords(at), rows: [row] });
  }
  return groups;
}

/** The team's lines as a timeline: an hour, then who did what in it. */
export function ActivityTimeline({
  rows,
  label,
  timeZone,
}: {
  rows: readonly TeamRow[];
  label: string;
  timeZone?: string;
}) {
  const go = useGo();
  return (
    <ol className={timeline.hours} aria-label={label}>
      {byHour(rows, timeZone).map((group) => (
        <li key={group.key} className={timeline.hour}>
          <span className={timeline.hourLabel}>
            {timeZone
              ? new Intl.DateTimeFormat(undefined, {
                  timeZone,
                  day: "numeric",
                  month: "short",
                  hour: "numeric",
                }).format(new Date(group.rows[0].at))
              : group.hour}
          </span>
          <ol className={timeline.lines}>
            {group.rows.map((row) => {
              const Icon = ICONS[row.kind] ?? Clock;
              const leadId = row.leadId;
              return (
                <li key={row.key}>
                  <Link
                    className={styles.activityRow}
                    href={row.report ? callHref(row.report) : "/leads"}
                    data-sx-action={row.report ? "report_open" : "lead_open"}
                    onClick={(click) => {
                      if (row.report || !leadId) return;
                      click.preventDefault();
                      handOverLead(leadId, false, row.at);
                      go("/leads");
                    }}
                  >
                    {/* The face is the sentence's subject; nobody's (a lead
                        came in) is the kind's mark alone. */}
                    {row.actor ? (
                      <span className={styles.who} aria-hidden="true">
                        <Avatar name={row.actor} size={32} />
                        <span className={styles.badge} data-kind={row.kind}>
                          <Icon size={11} />
                        </span>
                      </span>
                    ) : (
                      <span
                        className={styles.dot}
                        data-kind={row.kind}
                        aria-hidden="true"
                      >
                        <Icon size={15} />
                      </span>
                    )}
                    <span className={styles.words} data-sentence="">
                      <strong>{row.title}</strong>
                      {row.line ? <span>{row.line}</span> : null}
                    </span>
                    <time dateTime={row.at}>
                      {timeZone
                        ? new Intl.DateTimeFormat(undefined, {
                            timeZone,
                            hour: "numeric",
                            minute: "2-digit",
                          }).format(new Date(row.at))
                        : timeOfDay(new Date(row.at))}
                    </time>
                  </Link>
                  {row.recording ? (
                    <ActivityRecording submission={row.recording} />
                  ) : null}
                </li>
              );
            })}
          </ol>
        </li>
      ))}
    </ol>
  );
}

export function TeamActivity({
  saved,
}: {
  /** The latest saved calls Home already reads (the team's, for owners). */
  saved: readonly LibrarySubmission[] | null;
}) {
  const [work, setWork] = useState<Work>({ status: "loading" });
  const [now] = useState(() => new Date());
  const [all, setAll] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    readTeamActivity(controller.signal).then(
      (page) =>
        setWork({
          status: "ready",
          items: Array.isArray(page?.items) ? page.items : [],
        }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        // Not for this role, or not loaded: Team stays as it is.
        setWork({ status: "off" });
      },
    );
    return () => controller.abort();
  }, []);
  if (work.status === "off") return null;
  const every =
    work.status === "ready" ? teamRows(work.items, saved ?? [], now) : [];
  return (
    <section className={homeStyles.block} aria-labelledby="team-activity-title">
      <div className={homeStyles.head}>
        <h2 id="team-activity-title">Team today</h2>
        {every.length > TEAM_ROWS ? (
          <button
            type="button"
            className={`${styles.more} ${timeline.all}`}
            aria-haspopup="dialog"
            onClick={() => setAll(true)}
          >
            All activity
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        ) : (
          <Link className={styles.more} href="/organisation?tab=team">
            Team
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        )}
      </div>
      {work.status === "loading" ? (
        <CallRowsSkeleton label="Team today" rows={4} />
      ) : every.length === 0 ? (
        <p className={homeStyles.quiet}>
          Nothing yet today. Calls, notes, reports and lead moves show here as
          they happen.
        </p>
      ) : (
        <div className={timeline.card}>
          <ActivityTimeline
            rows={every.slice(0, TEAM_ROWS)}
            label="Team today, newest first"
          />
        </div>
      )}
      <Sheet
        open={all}
        onClose={() => setAll(false)}
        title="Team today"
        description={`${every.length} things so far today, newest first`}
        footer={
          <Link className={timeline.sheetLink} href="/organisation?tab=team">
            Open the team
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        }
      >
        {all ? (
          <ActivityTimeline rows={every} label="All of today, newest first" />
        ) : null}
      </Sheet>
    </section>
  );
}

/** Playback uses the existing authenticated source route and its consent/access gates. */
function ActivityRecording({ submission }: { submission: string }) {
  const [allowed, setAllowed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const player = useRef<HTMLAudioElement>(null);
  const source = `/v1/conversation/acquisition/submissions/${encodeURIComponent(submission)}/source`;
  useEffect(() => {
    const control = new AbortController();
    fetch(source, {
      credentials: "same-origin",
      headers: { Range: "bytes=0-0" },
      signal: control.signal,
    })
      .then(async (response) => {
        setAllowed(response.ok);
        await response.body?.cancel();
      })
      .catch(() => undefined);
    return () => control.abort();
  }, [source]);
  if (!allowed) return null;
  return (
    <div className={timeline.recording}>
      {playing ? (
        <audio
          ref={player}
          aria-label="Call recording"
          controls
          autoPlay
          src={source}
          onError={() => {
            setPlaying(false);
            notify({
              id: "activity-recording",
              tone: "error",
              title: "Recording couldn't play. Try again.",
            });
          }}
        />
      ) : (
        <button type="button" onClick={() => setPlaying(true)}>
          <Play size={14} aria-hidden /> Play recording
        </button>
      )}
    </div>
  );
}
