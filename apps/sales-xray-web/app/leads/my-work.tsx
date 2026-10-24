"use client";

/**
 * My work (owner, 24 Oct 2026, about a tester: "she has to see notes and work she has
 * done recently and she just can't"): everything the seller did on their leads, newest
 * first, today, yesterday or this week: calls, outcomes, notes, stage moves, meetings
 * and messages. A tap opens the lead at that line of its history.
 */

import {
  ArrowRightLeft,
  CalendarClock,
  Clock,
  MessageCircle,
  NotebookPen,
  Phone,
  type LucideIcon,
} from "lucide-react";
import { Fragment, useEffect, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Button, Empty, Segmented, Skeleton } from "../ui/kit";
import { eventText } from "./lead-sheet";
import {
  LeadsError,
  readActivity,
  type ActivityItem,
  type WorkDay,
} from "./leads-client";
import styles from "./my-work.module.css";

const DAYS: { key: WorkDay; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "week", label: "This week" },
];

const ICONS: Record<string, LucideIcon> = {
  call: Phone,
  result: Phone,
  note: NotebookPen,
  stage: ArrowRightLeft,
  meeting: CalendarClock,
  message: MessageCircle,
  scheduled: Clock,
};

/** The window's work in a few words: "12 calls · 3 notes · 5 stage moves". */
export function workWords(counts: Record<string, number>): string {
  // A call the phone logged and its outcome are one call.
  const calls = Math.max(counts.call ?? 0, counts.result ?? 0);
  const parts: [number, string, string][] = [
    [calls, "call", "calls"],
    [counts.note ?? 0, "note", "notes"],
    [counts.stage ?? 0, "stage move", "stage moves"],
    [counts.meeting ?? 0, "meeting", "meetings"],
    [counts.message ?? 0, "message", "messages"],
  ];
  return parts
    .filter(([count]) => count > 0)
    .map(([count, one, many]) => `${count} ${count === 1 ? one : many}`)
    .join(" · ");
}

/** A line of work in the seller's own words ("You talked to them: Interested"). */
export function workLine(item: ActivityItem): {
  title: string;
  detail?: string;
} {
  return eventText({ ...item.event, actor_name: "You" });
}

const clock = (at: string) =>
  new Date(at).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });

const dayOf = (at: string) =>
  new Date(at).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "short",
  });

type Loaded = {
  day: WorkDay;
  items: ActivityItem[];
  next: string | null;
  counts: Record<string, number>;
};

export function MyWork({
  onOpen,
  onStart,
}: {
  /** Open the lead at the line made at this time. */
  onOpen: (leadId: string, at: string) => void;
  /** An empty day's one action: start calling. */
  onStart?: () => void;
}) {
  const [day, setDay] = useState<WorkDay>("today");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [older, setOlder] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    readActivity(day, null, controller.signal).then(
      (page) =>
        setLoaded({
          day,
          items: page.items,
          next: page.next_before,
          counts: page.counts,
        }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        notify({
          id: "work-failed",
          tone: "error",
          title: "Your work didn't load",
          message: reason instanceof LeadsError ? reason.message : "Try again.",
        });
      },
    );
    return () => controller.abort();
  }, [day]);

  const shown = loaded && loaded.day === day ? loaded : null;

  const showOlder = async () => {
    if (!shown?.next) return;
    setOlder(true);
    try {
      const page = await readActivity(day, shown.next);
      setLoaded((value) =>
        value && value.day === day
          ? {
              ...value,
              items: [...value.items, ...page.items],
              next: page.next_before,
            }
          : value,
      );
    } catch (reason) {
      notify({
        id: "work-older-failed",
        tone: "error",
        title: "Older work didn't load",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    } finally {
      setOlder(false);
    }
  };

  const items = shown?.items ?? [];
  return (
    <section className={styles.work} aria-label="My work">
      <div className={styles.head}>
        <Segmented
          label="Which days"
          items={DAYS}
          value={day}
          onChange={setDay}
        />
        <p className={styles.summary} aria-live="polite">
          {shown ? workWords(shown.counts) || "Nothing yet" : " "}
        </p>
      </div>
      {!shown ? (
        <ol className={styles.list} aria-busy="true">
          {Array.from({ length: 6 }, (_, index) => (
            <li key={index} className={styles.skeleton}>
              <Skeleton width={32} height={32} />
              <Skeleton width="60%" height={14} />
            </li>
          ))}
        </ol>
      ) : items.length === 0 ? (
        <Empty
          icon={NotebookPen}
          title={
            day === "today"
              ? "Nothing yet today"
              : day === "yesterday"
                ? "Nothing yesterday"
                : "Nothing this week"
          }
          text="Calls, notes and stage moves you make show here, newest first."
          action={
            onStart && day === "today"
              ? { onClick: onStart, label: "Start calling" }
              : undefined
          }
        />
      ) : (
        <ol className={styles.list} aria-label="What you did, newest first">
          {items.map((item, index) => {
            const Icon = ICONS[item.event.kind] ?? Clock;
            const line = workLine(item);
            const newDay =
              day === "week" &&
              (index === 0 ||
                dayOf(items[index - 1].event.at) !== dayOf(item.event.at));
            return (
              <Fragment key={item.event_id}>
                {newDay ? (
                  <li className={styles.day} aria-hidden="true">
                    {dayOf(item.event.at)}
                  </li>
                ) : null}
                <li>
                  <button
                    type="button"
                    className={styles.row}
                    data-lead-row=""
                    onClick={() => onOpen(item.lead_id, item.event.at)}
                  >
                    <span
                      className={styles.icon}
                      data-kind={item.event.kind}
                      aria-hidden="true"
                    >
                      <Icon size={16} />
                    </span>
                    <span className={styles.text}>
                      <strong>{displayName(item.lead_name)}</strong>
                      <span>{line.title}</span>
                      {line.detail ? <small>{line.detail}</small> : null}
                    </span>
                    <time dateTime={item.event.at}>{clock(item.event.at)}</time>
                  </button>
                </li>
              </Fragment>
            );
          })}
        </ol>
      )}
      {shown?.next ? (
        <Button variant="ghost" onClick={showOlder} disabled={older}>
          {older ? "Loading…" : "Show older"}
        </Button>
      ) : null}
    </section>
  );
}
