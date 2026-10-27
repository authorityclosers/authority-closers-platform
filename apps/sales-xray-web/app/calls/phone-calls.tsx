"use client";

/**
 * Your calls, first on Calls (owner, 27 Oct 2026: "There has to be a very
 * easy way to see all call logs, call recordings… it's hidden somewhere" and
 * "it's really hard for her to see who she called"). The calls you made or
 * took with your leads this week, newest first, missed and incoming ones too
 * (the phone app puts dialer calls on their lead by itself). A tap opens the
 * call's Report when it has one, otherwise the lead at that call. With them,
 * the recordings the phone holds for analysis and the work calls from numbers
 * that aren't leads yet. Saved calls follow on the page. It reuses My work's
 * read (GET /v1/lead-desk/activity) and Leads' phone cards; nothing new.
 */

import {
  ChevronRight,
  PhoneIncoming,
  PhoneMissed,
  PhoneOff,
  PhoneOutgoing,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useEffect, useState } from "react";

import { callHref } from "../acquisition-client";
import { displayName } from "../display-name";
import { AddLeadDialog } from "../leads/capture-dialogs";
import { handOverLead } from "../leads/lead-handoff";
import {
  LeadsError,
  readActivity,
  type ActivityItem,
  type LeadEvent,
} from "../leads/leads-client";
import { uniqueEvents } from "../leads/my-work";
import { forgetUnknown } from "../leads/native-phone";
import { clockTime } from "../leads/phone-call-text";
import { PhoneLogCard } from "../leads/phone-log-card";
import { RecordedCallsCard } from "../leads/recorded-calls";
import { UnknownCallsCard } from "../leads/unknown-calls-card";
import { Avatar, Skeleton } from "../ui/kit";
import styles from "./phone-calls.module.css";

/** Calls on the Calls page; the rest are in My work, with notes and moves. */
export const SHOWN_CALLS = 6;
const MY_WORK = "/leads?tab=work";

/** "You called · 3:12", "They called · 1:05", "Missed call": the seller's side. */
export function callLine(event: LeadEvent): string {
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
    default:
      if (event.simulated) return "Sample call";
      if (talk) return `You called · ${talk}`;
      return event.via === "phone" ? "You called · no answer" : "You called";
  }
}

const ICONS: Record<string, LucideIcon> = {
  incoming: PhoneIncoming,
  missed: PhoneMissed,
  rejected: PhoneMissed,
  blocked: PhoneOff,
};

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

/** This week's calls, newest first, each once; nothing from an odd answer. */
export function weekCalls(items: unknown): ActivityItem[] {
  if (!Array.isArray(items)) return [];
  return uniqueEvents(items as ActivityItem[]).filter(
    (item) => item?.event?.kind === "call",
  );
}

type Calls =
  | { status: "loading" }
  | { status: "ready"; items: ActivityItem[]; more: boolean }
  | { status: "error" }
  // Outside an organisation, or signed out: Calls shows saved calls only.
  | { status: "off" };

export function PhoneCalls() {
  const router = useRouter();
  const [state, setState] = useState<Calls>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [unknown, setUnknown] = useState<string | null>(null);
  const [now] = useState(() => new Date());

  useEffect(() => {
    const controller = new AbortController();
    readActivity("week", null, controller.signal).then(
      (page) => {
        const calls = weekCalls(page?.items);
        setState({
          status: "ready",
          items: calls.slice(0, SHOWN_CALLS),
          more: calls.length > SHOWN_CALLS || Boolean(page?.next_before),
        });
      },
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
  }, [attempt]);

  if (state.status === "off") return null;
  const items = state.status === "ready" ? state.items : [];

  return (
    <section className={styles.calls} aria-labelledby="your-calls-title">
      <div className={styles.head}>
        <h2 id="your-calls-title">Your calls</h2>
        {state.status === "ready" && items.length ? (
          <Link className={styles.more} href={MY_WORK}>
            My work
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        ) : null}
      </div>
      <PhoneLogCard as="offer" />
      <RecordedCallsCard />
      {state.status === "loading" ? (
        <ol className={styles.list} aria-busy="true" aria-label="Your calls">
          {Array.from({ length: 3 }, (_, index) => (
            <li key={index} className={styles.skeleton}>
              <Skeleton width={36} height={36} radius="circle" />
              <span>
                <Skeleton width="55%" height={14} />
                <Skeleton width="35%" height={12} />
              </span>
            </li>
          ))}
        </ol>
      ) : state.status === "error" ? (
        <div className={styles.quiet} role="status">
          <span>Your calls didn&apos;t load.</span>
          <button
            type="button"
            className={styles.retry}
            onClick={() => {
              setState({ status: "loading" });
              setAttempt((value) => value + 1);
            }}
          >
            Try again
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className={styles.quiet}>
          <span>
            No calls this week yet. Calls with your leads show here, missed ones
            too.
          </span>
          <Link className={styles.retry} href="/leads">
            Call a lead
          </Link>
        </div>
      ) : (
        <ol className={styles.list} aria-label="Your calls, newest first">
          {items.map((item, index) => {
            const event = item.event;
            const Icon = ICONS[event.direction ?? ""] ?? PhoneOutgoing;
            const report = event.submission_id;
            const day = dayLabel(event.at, now);
            const newDay =
              index === 0 || dayLabel(items[index - 1].event.at, now) !== day;
            const missed =
              event.direction === "missed" || event.direction === "rejected";
            return (
              <Fragment key={item.event_id}>
                {newDay ? (
                  <li className={styles.day} aria-hidden="true">
                    {day}
                  </li>
                ) : null}
                <li>
                  <Link
                    className={styles.row}
                    href={report ? callHref(report) : "/leads"}
                    data-sx-action={report ? "report_open" : "lead_open"}
                    data-missed={missed ? "" : undefined}
                    onClick={(click) => {
                      if (report) return;
                      click.preventDefault();
                      handOverLead(item.lead_id, false, event.at);
                      router.push("/leads");
                    }}
                  >
                    <Avatar name={item.lead_name} size={36} />
                    <span className={styles.text}>
                      <strong>{displayName(item.lead_name)}</strong>
                      <span className={styles.line}>
                        <Icon size={14} aria-hidden="true" />
                        {callLine(event)}
                      </span>
                    </span>
                    <span className={styles.end}>
                      <time dateTime={event.at}>{clock(event.at)}</time>
                      {report ? (
                        <span className={styles.report}>Report</span>
                      ) : null}
                    </span>
                  </Link>
                </li>
              </Fragment>
            );
          })}
        </ol>
      )}
      {state.status === "ready" && state.more ? (
        <Link className={styles.all} href={MY_WORK}>
          See all in My work
        </Link>
      ) : null}
      <UnknownCallsCard onSave={setUnknown} />
      {unknown ? (
        <AddLeadDialog
          key={`unknown-${unknown}`}
          open
          canManage={false}
          initial={{ name: "", phone: unknown, email: "", note: "" }}
          initialNote="A work call on your phone. Add their name, then add the lead."
          onClose={() => setUnknown(null)}
          onAdded={(leadId) => {
            void forgetUnknown(unknown);
            setUnknown(null);
            handOverLead(leadId);
            router.push("/leads");
          }}
        />
      ) : null}
    </section>
  );
}
