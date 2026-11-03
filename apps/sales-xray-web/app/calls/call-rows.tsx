"use client";

/**
 * Call rows: one way to show a call wherever calls are listed, on Calls (Your
 * calls) and on Home (Recent), owner 27 Oct 2026: "really hard for her to see
 * who she called". Each row has the lead's name with capitals, who called whom
 * and for how long (missed calls in red), the time, and a Report chip when the
 * call has one. A tap opens the Report, or else the lead at that call. Phone
 * calls come from My work's read; saved calls from the calls list.
 */

import {
  AudioLines,
  PhoneIncoming,
  PhoneMissed,
  PhoneOff,
  PhoneOutgoing,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";

import { callHref, type LibrarySubmission } from "../acquisition-client";
import { callTitle } from "../call-label";
import { displayName } from "../display-name";
import { AutoCaptureState } from "../leads/auto-capture-state";
import { handOverLead } from "../leads/lead-handoff";
import {
  LeadsError,
  readActivity,
  readDayCalls,
  type ActivityItem,
  type ActivityPage,
  type LeadEvent,
} from "../leads/leads-client";
import { clockTime } from "../leads/phone-call-text";
import { useAppRouter } from "../shell/app-router";
import { Avatar } from "../ui/kit";
import styles from "./phone-calls.module.css";

/** "You called · 3:12", "They called · 1:05", "Missed call": the seller's
 *  side. Where the seconds came from when the read says, and "outcome
 *  unknown" when the phone never said how a dial went (owner and Dipak, 2 Nov
 *  2026). `caller`: who made a call out. */
export function callLine(event: LeadEvent, caller = "You"): string {
  const talk = event.duration_seconds ? clockTime(event.duration_seconds) : "";
  const from =
    event.seconds_from === "recording"
      ? " from the phone's recording"
      : event.seconds_from === "call_log"
        ? " from call history"
        : "";
  switch (event.direction) {
    case "incoming":
      return talk ? `They called · ${talk}${from}` : "They called";
    case "missed":
      return "Missed call";
    case "rejected":
      return "You cut their call";
    case "blocked":
      return "Blocked call";
    default:
      if (event.simulated) return "Sample call";
      if (event.outcome === "unknown")
        return `${caller} called · outcome unknown`;
      if (talk) return `${caller} called · ${talk}${from}`;
      return event.via === "phone" || event.outcome === "not_connected"
        ? `${caller} called · no answer`
        : `${caller} called`;
  }
}

/** Home's line for a call: its outcome in a word or two, with its length
 *  when it connected (Dipak's picture, 2 Nov 2026: "Connected · 11:20 AM";
 *  the time is the row's own). Calls says where the seconds came from. */
export function outcomeLine(event: LeadEvent): string {
  const talk = event.duration_seconds ? clockTime(event.duration_seconds) : "";
  switch (event.direction) {
    case "incoming":
      return talk ? `They called · ${talk}` : "They called";
    case "missed":
      return "Missed call";
    case "rejected":
      return "You cut their call";
    case "blocked":
      return "Blocked call";
  }
  if (event.simulated) return "Sample call";
  if (event.outcome === "unknown") return "Outcome unknown";
  if (talk) return `Connected · ${talk}`;
  if (event.outcome === "connected") return "Connected";
  return event.outcome === "not_connected" || event.via === "phone"
    ? "No answer"
    : "Called";
}

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** "Today", "Yesterday", or "Monday 26 Oct". */
export function dayLabel(at: string, now: Date = new Date()): string {
  const day = new Date(at);
  if (sameDay(day, now)) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(day, yesterday)) return "Yesterday";
  return day.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "short",
  });
}

const clock = (at: string) =>
  new Date(at).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });

/** Without day headings: the time today, else "Yesterday" or the weekday. */
export function shortWhen(at: string, now: Date = new Date()): string {
  const day = dayLabel(at, now);
  if (day === "Today") return clock(at);
  if (day === "Yesterday") return day;
  return new Date(at).toLocaleDateString(undefined, { weekday: "short" });
}

/** Moves to a screen in the app, or loads it where no app router is mounted
 *  (tests, static previews): next/navigation's useRouter throws there. */
export function useGo(): (href: string) => void {
  const router = useAppRouter();
  return useCallback(
    (href: string) => {
      if (router) router.push(href);
      else window.location.assign(href);
    },
    [router],
  );
}

/** A call as a row shows it, from the phone's call log or the calls list. */
export type CallRow = {
  key: string;
  /** Display-ready: capitals, or the call's own name. */
  name: string;
  at: string;
  line: string;
  kind: "outgoing" | "incoming" | "missed" | "blocked" | "saved";
  /** The saved call whose Report a tap opens, or null. */
  report: string | null;
  leadId: string | null;
  /** A connected phone call with a lead: it shows its way to a Report (dialled → report ready). */
  talked?: boolean;
};

export function rowFromActivity(item: ActivityItem): CallRow {
  const direction = item.event.direction;
  return {
    key: item.event_id,
    name: displayName(item.lead_name),
    at: item.event.at,
    line: callLine(item.event),
    kind:
      direction === "missed" || direction === "rejected"
        ? "missed"
        : direction === "incoming" || direction === "blocked"
          ? direction
          : "outgoing",
    report: item.event.submission_id ?? null,
    leadId: item.lead_id,
    talked:
      Boolean(item.event.duration_seconds) &&
      !item.event.simulated &&
      (direction === "outgoing" || direction === "incoming" || !direction),
  };
}

/** A seller's or the team's call: who made it, by their first name. */
export function rowFromTheirs(item: ActivityItem): CallRow {
  const caller = item.event.actor_name
    ? displayName(item.event.actor_name).split(" ")[0]
    : "A seller";
  return { ...rowFromActivity(item), line: callLine(item.event, caller) };
}

/** Calls opened from a number (owner, 2 Nov 2026): one day's calls, the
 *  viewer's own, a seller's or the team's, one side's, with one outcome. */
export type CallsFilter = {
  day: "today" | "yesterday";
  person: string | null;
  team: boolean;
  side: "inbound" | "cold" | null;
  outcome: "connected" | "not_connected" | "unknown" | "known" | null;
};

const OUTCOMES = ["connected", "not_connected", "unknown", "known"] as const;

/** The filter in Calls' address, or null without one (the week's calls). */
export function callsFilter(params: URLSearchParams): CallsFilter | null {
  const day = params.get("day");
  if (day !== "today" && day !== "yesterday") return null;
  const side = params.get("side");
  const outcome = params.get("outcome");
  return {
    day,
    person: params.get("person"),
    team: params.get("team") === "1",
    side: side === "cold" || side === "inbound" ? side : null,
    outcome: OUTCOMES.find((value) => value === outcome) ?? null,
  };
}

// Not calls out (the store's NOT_OUT): every number that opens Calls counts calls out.
const NOT_OUT = new Set(["incoming", "missed", "rejected", "blocked"]);

/** Whether the filter counts this call: a call out, as the number that opened it. */
export function inFilter(item: ActivityItem, filter: CallsFilter): boolean {
  if (NOT_OUT.has(item.event.direction ?? "")) return false;
  if (filter.side && item.side && item.side !== filter.side) return false;
  const outcome = item.event.outcome;
  if (filter.outcome === "known") return outcome !== "unknown";
  return filter.outcome === null || outcome === filter.outcome;
}

const OUTCOME_WORDS: Record<NonNullable<CallsFilter["outcome"]>, string> = {
  connected: "connected",
  not_connected: "not connected",
  unknown: "outcome unknown",
  known: "outcome known",
};

/** "Today's calls · outcome unknown". */
export function filterTitle(filter: CallsFilter): string {
  const day = filter.day === "today" ? "Today's calls" : "Yesterday's calls";
  return filter.outcome ? `${day} · ${OUTCOME_WORDS[filter.outcome]}` : day;
}

export function rowFromSaved(call: LibrarySubmission): CallRow {
  const talk = call.durationSeconds > 0 ? clockTime(call.durationSeconds) : "";
  return {
    key: `saved-${call.id}`,
    name: call.lead
      ? displayName(call.lead.name)
      : callTitle(call.label, "Saved call"),
    at: call.createdAt,
    line: `${call.hasReport ? "Report ready" : call.state === "processing" ? "Analysing" : "Saved call"}${talk ? ` · ${talk}` : ""}`,
    kind: "saved",
    report: call.id,
    leadId: call.lead?.leadId ?? null,
  };
}

/** Phone and saved calls, newest first; a phone call saved for analysis shows once. */
export function mergeCalls(
  phone: readonly CallRow[],
  saved: readonly CallRow[],
): CallRow[] {
  const joined = new Set(phone.map((row) => row.report).filter(Boolean));
  return [...phone, ...saved.filter((row) => !joined.has(row.report))].sort(
    (a, b) => Date.parse(b.at) - Date.parse(a.at),
  );
}

/** Each event once (as My work: an older page can repeat a few), without
 *  importing My work and the lead page with it. */
function uniqueEvents(items: readonly ActivityItem[]): ActivityItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (!item || seen.has(item.event_id)) return false;
    seen.add(item.event_id);
    return true;
  });
}

/** This week's calls, newest first, each once; nothing from an odd answer. */
export function weekCalls(items: unknown): ActivityItem[] {
  if (!Array.isArray(items)) return [];
  return uniqueEvents(items as ActivityItem[]).filter(
    (item) => item?.event?.kind === "call",
  );
}

export type WeekActivity =
  | { status: "loading" }
  | { status: "ready"; items: ActivityItem[]; more: boolean }
  | { status: "error" }
  // Outside an organisation, or signed out.
  | { status: "off" };

/** A day's calls, every page of them (a team's day can run past one). */
async function dayCalls(
  filter: CallsFilter,
  signal: AbortSignal,
): Promise<ActivityPage> {
  const items: ActivityItem[] = [];
  let before: string | null = null;
  for (let page = 0; page < 5; page += 1) {
    const read: ActivityPage = await readDayCalls(
      filter.day,
      filter,
      before,
      signal,
    );
    if (Array.isArray(read?.items)) items.push(...read.items);
    before = read?.next_before ?? null;
    if (!before) break;
  }
  return { items, next_before: before, counts: {} };
}

/** This week's own work (My work's read), once per mount, with a retry;
 *  with a filter, that day's calls (Calls opened from a number). */
export function useWeekActivity(
  filter: CallsFilter | null = null,
): [WeekActivity, () => void] {
  const [state, setState] = useState<WeekActivity>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const day = filter?.day;
  const person = filter?.person ?? null;
  const team = filter?.team ?? false;
  useEffect(() => {
    const controller = new AbortController();
    (day
      ? dayCalls(
          { day, person, team, side: null, outcome: null },
          controller.signal,
        )
      : readActivity("week", null, controller.signal)
    ).then(
      (page) =>
        setState({
          status: "ready",
          items: Array.isArray(page?.items) ? uniqueEvents(page.items) : [],
          more: Boolean(page?.next_before),
        }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setState(
          reason instanceof LeadsError &&
            [401, 403, 404].includes(reason.status)
            ? { status: "off" }
            : { status: "error" },
        );
      },
    );
    return () => controller.abort();
  }, [attempt, day, person, team]);
  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  }, []);
  return [state, retry];
}

const ICONS: Record<CallRow["kind"], LucideIcon> = {
  outgoing: PhoneOutgoing,
  incoming: PhoneIncoming,
  missed: PhoneMissed,
  blocked: PhoneOff,
  saved: AudioLines,
};

/**
 * `days`: a heading per day (Calls); without, each row says when (Home).
 */
export function CallRows({
  rows,
  now,
  label,
  days = true,
}: {
  rows: readonly CallRow[];
  now: Date;
  label: string;
  days?: boolean;
}) {
  const go = useGo();
  return (
    <ol className={styles.list} aria-label={label}>
      {rows.map((row, index) => {
        const Icon = ICONS[row.kind];
        const day = dayLabel(row.at, now);
        const newDay =
          days && (index === 0 || dayLabel(rows[index - 1].at, now) !== day);
        const leadId = row.leadId;
        return (
          <Fragment key={row.key}>
            {newDay ? (
              <li className={styles.day} aria-hidden="true">
                {day}
              </li>
            ) : null}
            <li>
              <Link
                className={styles.row}
                href={row.report ? callHref(row.report) : "/leads"}
                data-sx-action={row.report ? "report_open" : "lead_open"}
                data-missed={row.kind === "missed" ? "" : undefined}
                onClick={(click) => {
                  if (row.report || !leadId) return;
                  click.preventDefault();
                  handOverLead(leadId, false, row.at);
                  go("/leads");
                }}
              >
                <Avatar name={row.name} size={36} />
                <span className={styles.text}>
                  <strong>{row.name}</strong>
                  <span className={styles.line}>
                    <Icon size={14} aria-hidden="true" />
                    {row.line}
                  </span>
                  {row.talked && !row.report ? (
                    <AutoCaptureState eventId={row.key} links={false} />
                  ) : null}
                </span>
                <span className={styles.end}>
                  <time dateTime={row.at}>
                    {days ? clock(row.at) : shortWhen(row.at, now)}
                  </time>
                  {row.report ? (
                    <span className={styles.report}>Report</span>
                  ) : null}
                </span>
              </Link>
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}
