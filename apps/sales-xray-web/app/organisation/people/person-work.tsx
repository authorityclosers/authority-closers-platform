"use client";

import { useEffect, useState } from "react";
import {
  ActivityTimeline,
  rowFromWork,
  rowFromReport,
} from "../../dashboard/team-activity";
import { readPersonWork, type ActivityPage } from "../../leads/leads-client";
import { notify } from "../../notice-center";
import { Skeleton } from "../../ui/kit";
import type { PersonCall } from "./person-data";
import styles from "./person-work.module.css";

function Count({ value }: { value: number }) {
  const [shown, setShown] = useState(value);
  useEffect(() => {
    if (!window.matchMedia?.("(prefers-reduced-motion: no-preference)").matches)
      return;
    let frame = 0;
    const start = performance.now();
    const draw = (now: number) => {
      const fraction = Math.min(1, (now - start) / 240);
      setShown(Math.round(value * fraction));
      if (fraction < 1) frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <strong aria-label={String(value)}>{shown}</strong>;
}

const ago = (at: string) => {
  const minutes = Math.max(
    0,
    Math.floor((Date.now() - Date.parse(at)) / 60000),
  );
  return minutes < 1
    ? "just now"
    : minutes < 60
      ? `${minutes} min ago`
      : minutes < 1440
        ? `${Math.floor(minutes / 60)} ${Math.floor(minutes / 60) === 1 ? "hour" : "hours"} ago`
        : `${Math.floor(minutes / 1440)} ${Math.floor(minutes / 1440) === 1 ? "day" : "days"} ago`;
};
export function activityDay(at: string, timeZone: string, now = new Date()) {
  const key = (date: Date) =>
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
  if (key(new Date(at)) === key(now)) return "Today";
  if (key(new Date(at)) === key(new Date(now.getTime() - 86400000)))
    return "Yesterday";
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(at));
}

export function PersonWork({
  personId,
  saved = [],
}: {
  personId: string;
  saved?: readonly PersonCall[];
}) {
  const [page, setPage] = useState<ActivityPage | null>(null);
  const [shown, setShown] = useState(10);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const control = new AbortController();
    readPersonWork(personId, null, control.signal)
      .then((value) => {
        if (!control.signal.aborted) setPage(value);
      })
      .catch(() => {
        if (control.signal.aborted) return;
        setFailed(true);
        notify({
          id: "person-work",
          tone: "error",
          title: "Recent activity didn't load",
          action: {
            label: "Try again",
            run: () => {
              setFailed(false);
              setAttempt((n) => n + 1);
            },
          },
        });
      });
    return () => control.abort();
  }, [personId, attempt]);
  const more = async () => {
    if (!page || busy) return;
    if (shown < rows.length) {
      setShown((n) => n + 10);
      return;
    }
    if (!page.next_before) return;
    setBusy(true);
    try {
      const next = await readPersonWork(personId, page.next_before);
      setPage({
        ...next,
        items: [
          ...page.items,
          ...next.items.filter(
            (item) => !page.items.some((old) => old.event_id === item.event_id),
          ),
        ],
      });
      setShown((n) => n + 10);
    } catch {
      notify({
        id: "person-work-more",
        tone: "error",
        title: "More activity didn't load. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  if (!page)
    return (
      <section
        className={styles.work}
        aria-label="Loading recent activity"
        aria-busy={!failed}
      >
        {failed ? (
          <button
            type="button"
            onClick={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </button>
        ) : (
          <>
            <div className={styles.presence}>
              <Skeleton width="55%" height={18} />
              <Skeleton width="45%" height={14} />
            </div>
            <div className={styles.strip}>
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} height={100} />
              ))}
            </div>
            <h2>Recent activity</h2>
            <Skeleton height={300} />
          </>
        )}
      </section>
    );
  const work = page.items.map(rowFromWork);
  const linked = new Set(work.map((row) => row.report).filter(Boolean));
  const uploads = saved
    .filter((call) => !linked.has(call.id))
    .map((call) => {
      const row = rowFromReport({ ...call, owner: { name: call.ownerName } });
      return call.hasReport
        ? row
        : {
            ...row,
            key: `upload-${call.id}`,
            title: `Recorded call: ${call.label ?? "Saved call"}`,
            kind: "call",
            recording: call.id,
          };
    });
  const rows = [...work, ...uploads].sort(
    (a, b) => Date.parse(b.at) - Date.parse(a.at),
  );
  const today = page.today_counts ?? {};
  const week = page.week_counts ?? {};
  const zone = page.timezone ?? "Asia/Kolkata";
  const last = rows[0]?.at ?? page.last_active_at;
  const day = last ? activityDay(last, zone) : null;
  const figures = [
    ["call", "Calls"],
    ["connected", "Conversations"],
    ["note", "Notes"],
    ["stage", "Stage moves"],
  ];
  return (
    <section className={styles.work} aria-label="Recent activity">
      <p className={styles.presence}>
        {last ? `Last active ${ago(last)}` : "No work recorded yet"}
        {page.last_call_at ? (
          <span>Last call {ago(page.last_call_at)}</span>
        ) : null}
      </p>
      {rows.length || Object.values(week).some((value) => value > 0) ? (
        <div className={styles.strip} aria-label="Today and the last 7 days">
          {figures.map(([kind, label], index) => (
            <div
              className={styles.figure}
              key={kind}
              style={{ animationDelay: `${index * 35}ms` }}
            >
              <span>{label}</span>
              <Count value={today[kind] ?? 0} />
              <small>today · {week[kind] ?? 0} in 7 days</small>
            </div>
          ))}
        </div>
      ) : null}
      <div className={styles.heading}>
        <h2>Recent activity</h2>
        {day ? <span>{day}</span> : null}
      </div>
      {day && day !== "Today" ? (
        <p className={styles.quiet}>
          Quiet today. Here&apos;s the most recent working day and earlier
          activity.
        </p>
      ) : null}
      {rows.length ? (
        <div className={styles.timeline}>
          <ActivityTimeline
            rows={rows.slice(0, shown)}
            label="Recent activity, newest first"
            timeZone={zone}
          />
        </div>
      ) : (
        <p className={styles.quiet}>
          Calls, notes, messages and follow-ups will appear here.{" "}
          <a className={styles.primary} href="/leads">
            Open leads
          </a>
        </p>
      )}
      {shown < rows.length || page.next_before ? (
        <button
          className={styles.more}
          type="button"
          disabled={busy}
          onClick={() => void more()}
        >
          {busy ? "Loading…" : "Show more"}
        </button>
      ) : null}
    </section>
  );
}
