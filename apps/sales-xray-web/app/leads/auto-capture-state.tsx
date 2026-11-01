"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  autoCaptureStates,
  onPhoneSignal,
  type AutoCaptureItem,
} from "./native-phone";
import { readCaptureGuard, type CaptureCall } from "./capture-guard-client";
import { RecordingFix } from "../capture-guard/recording-fix";
import styles from "../capture-guard/capture-guard.module.css";

const labels: Record<string, string> = {
  waiting: "Waiting for recording",
  unavailable: "Recording status unavailable",
  uploading: "Uploading",
  uploaded: "Uploaded",
  analysing: "Analysing",
  report_ready: "Report ready",
  // Under the short-call rule (owner, 21 Oct 2026): done, with no report.
  short_call: "Short call · transcript and lead details",
  missing: "No recording after 30 minutes",
  cancelled: "Upload cancelled",
  held: "Upload paused · review this call",
};
// Why the phone holds a call (app builds with autoCaptureHealth, 30 Oct 2026); it uploads by itself once fixed.
const holds: Record<string, { label: string; href: string }> = {
  profile: {
    label: "Waiting · complete your profile",
    href: "/settings/profile",
  },
  allowance: {
    label: "Waiting for call minutes",
    href: "/settings/privacy#calls-setup",
  },
  signed_out: {
    label: "Waiting · sign in on your phone",
    href: "/settings/privacy#calls-setup",
  },
  workspace: {
    label: "Waiting · switch to your organisation",
    href: "/settings/privacy#calls-setup",
  },
  folder: {
    label: "Waiting · pick the recordings folder",
    href: "/settings/privacy#calls-setup",
  },
  network: {
    label: "Waiting · phone blocks background uploads",
    href: "/settings/privacy#calls-setup",
  },
  access: {
    label: "Waiting · tried again every hour",
    href: "/settings/privacy#calls-setup",
  },
  consent: {
    label: "Paused · automatic uploads are off",
    href: "/settings/privacy#automatic-call-uploads",
  },
  notices: {
    label: "Paused · upload notices are off",
    href: "/settings/privacy#automatic-call-uploads",
  },
  off: {
    label: "Paused · uploads are off",
    href: "/settings/privacy#automatic-call-uploads",
  },
  expired: {
    label: "Too old to upload by itself",
    href: "/settings/privacy#calls-setup",
  },
};
export function CaptureStateLabel({
  state,
  attention = false,
  hold,
}: {
  state: string;
  attention?: boolean;
  /** Why the phone holds this call (newer app builds). */
  hold?: string | null;
}) {
  const held = state === "held" && hold ? holds[hold] : undefined;
  return (
    <span className={styles.state} data-missing={state === "missing"}>
      <small role="status">
        {held?.label ?? labels[state]}
        {attention ? " · Analysis needs attention" : ""}
      </small>
      {held ? (
        <Link href={held.href}>
          {hold === "profile" ? "Open Profile" : "Fix uploads"}
        </Link>
      ) : state === "missing" || state === "cancelled" || state === "held" ? (
        <RecordingFix label="Fix recording" />
      ) : null}
    </span>
  );
}
/** Every call's way to its Report (owner, 30 Oct 2026: "I need each single call getting tracked"). */
export const TRACK_STEPS = [
  "Dialled",
  "Recorded",
  "Matched",
  "Waiting",
  "Uploaded",
  "Analysing",
  "Report ready",
] as const;
export type Track = {
  /** The last step done (0 = dialled); the next one is where the call is, or is stuck. */
  done: number;
  label: string;
  stuck: boolean;
  /** Finished before the last step: a short call has a transcript and no report. */
  ended?: boolean;
  /** sheet: the recording check opens over the call (Back returns to it); else a link. */
  fix?: { label: string; href: string; sheet?: boolean };
  /** Where the recording is (competitor teardown #7): said first on the row. */
  recording?: "arrived" | "waiting" | "not found";
};
const setupFix = {
  label: "Fix recording",
  href: "/settings/privacy#calls-setup",
  sheet: true,
};
/**
 * The phone's queue (app builds with autoCaptureHealth add a hold reason) and the capture guard's
 * receipts. A hold says why a call waits, so it leads; then server receipts, which outrank a stale
 * native queue; missing stays visible after the deadline.
 */
export function trackFor(
  native: AutoCaptureItem | null,
  server: CaptureCall | null,
  unavailable = false,
): Track | null {
  const arrived = "arrived" as const;
  if (server?.state === "report_ready")
    return {
      done: 6,
      label: "Report ready",
      stuck: false,
      recording: arrived,
    };
  if (server?.state === "short_call")
    return {
      done: 5,
      label: labels.short_call,
      stuck: false,
      ended: true,
      recording: arrived,
    };
  if (server?.attention)
    return {
      done: 4,
      label: "Analysis stopped · the AC team sees it in Health",
      stuck: true,
      recording: arrived,
    };
  if (server?.state === "analysing")
    return { done: 4, label: "Analysing", stuck: false, recording: arrived };
  if (server?.state === "uploaded")
    return { done: 4, label: "Uploaded", stuck: false, recording: arrived };
  if (native?.state === "held") {
    const held = native.hold ? holds[native.hold] : undefined;
    return {
      done: 2,
      label: held?.label ?? labels.held,
      stuck: true,
      recording: arrived,
      fix: held
        ? {
            label: native.hold === "profile" ? "Open Profile" : "Fix uploads",
            href: held.href,
            // Privacy's checks open over the call; the profile is its own page.
            sheet: held.href.startsWith("/settings/privacy#"),
          }
        : setupFix,
    };
  }
  if (native?.state === "cancelled")
    return {
      done: 2,
      label: "Upload cancelled · the recording stays on the phone",
      stuck: true,
      recording: arrived,
      fix: setupFix,
    };
  // No recording 30 minutes on: a call that ended without one, said calmly with its way to
  // add it, never "Stuck" in red (persona QA, 31 Oct 2026: it shouted two days later).
  if (server?.state === "missing")
    return {
      done: 0,
      label: labels.missing,
      stuck: false,
      ended: true,
      fix: setupFix,
      recording: "not found",
    };
  if (native?.state === "report_ready")
    return { done: 6, label: "Report ready", stuck: false, recording: arrived };
  if (native?.state === "analysing")
    return { done: 4, label: "Uploaded", stuck: false, recording: arrived };
  if (native?.state === "uploading")
    return { done: 3, label: "Uploading", stuck: false, recording: arrived };
  if (native?.state === "waiting")
    return {
      done: 2,
      label: "Waiting to upload",
      stuck: false,
      recording: arrived,
    };
  if (server?.state === "waiting")
    return {
      done: 0,
      label: labels.waiting,
      stuck: false,
      recording: "waiting",
    };
  if (unavailable) return { done: -1, label: labels.unavailable, stuck: false };
  return null;
}

/** Dots for the seven steps, where the call is, and its one fix. links: false inside a row that is a link. */
export function CallTrack({
  track,
  links = true,
}: {
  track: Track;
  links?: boolean;
}) {
  const at = TRACK_STEPS[Math.min(track.done + 1, TRACK_STEPS.length - 1)];
  return (
    <span
      className={styles.track}
      data-stuck={track.stuck || undefined}
      data-missing={track.stuck && track.done === 0 ? "true" : undefined}
    >
      {track.done >= 0 ? (
        <span
          className={styles.steps}
          role="img"
          aria-label={
            track.done >= TRACK_STEPS.length - 1
              ? "All 7 steps done"
              : track.ended
                ? `Done after ${TRACK_STEPS[track.done]}, no report`
                : `${track.stuck ? "Stuck at" : "Now at"} ${at}, step ${track.done + 2} of 7`
          }
        >
          {TRACK_STEPS.map((step, index) => (
            <i
              key={step}
              data-done={index <= track.done || undefined}
              data-now={(!track.ended && index === track.done + 1) || undefined}
            />
          ))}
        </span>
      ) : null}
      <small role="status">
        {track.recording && track.recording !== "arrived"
          ? // Waiting or not found: the recording is the whole story.
            `Recording: ${track.recording}`
          : `${track.recording ? "Recording: arrived · " : ""}${track.stuck ? "Stuck · " : ""}${track.label}`}
      </small>
      {links && track.fix ? (
        track.fix.sheet ? (
          <RecordingFix label={track.fix.label} />
        ) : (
          <Link href={track.fix.href}>{track.fix.label}</Link>
        )
      ) : null}
    </span>
  );
}

type Evidence = {
  native: AutoCaptureItem | null;
  server: CaptureCall | null;
  unavailable: boolean;
};
// One read for every call on screen, every 30 s and on the phone's signals, not one per row.
const watchers = new Map<string, Set<(evidence: Evidence) => void>>();
let reading: Promise<void> | null = null;
let again = false;
let timer: ReturnType<typeof setInterval> | null = null;
let stopSignal: (() => void) | null = null;
async function readAll(): Promise<void> {
  const ids = [...watchers.keys()];
  if (!ids.length) return;
  const [items, recent] = await Promise.all([
    autoCaptureStates(),
    readCaptureGuard(),
  ]);
  // An older call than the guard's week is read on its own.
  const older = recent
    ? ids.filter((id) => !recent.calls.some((call) => call.event_id === id))
    : [];
  const extra = await Promise.all(older.map((id) => readCaptureGuard(id)));
  const calls = [
    ...(recent?.calls ?? []),
    ...extra.flatMap((read) => read?.calls ?? []),
  ];
  for (const id of ids) {
    const evidence: Evidence = {
      native: items.find((item) => item.eventId === id) ?? null,
      server: calls.find((call) => call.event_id === id) ?? null,
      unavailable: recent === null,
    };
    watchers.get(id)?.forEach((tell) => tell(evidence));
  }
}
function look(): void {
  if (reading) {
    again = true;
    return;
  }
  reading = readAll()
    .catch(() => undefined)
    .finally(() => {
      reading = null;
      if (again) {
        again = false;
        look();
      }
    });
}
export function watchCapture(
  eventId: string,
  tell: (evidence: Evidence) => void,
): () => void {
  const set = watchers.get(eventId) ?? new Set();
  set.add(tell);
  watchers.set(eventId, set);
  if (!timer) {
    timer = setInterval(look, 30_000);
    stopSignal = onPhoneSignal((signal) => {
      if (signal === "recordings" || signal === "resume") look();
    });
  }
  look();
  return () => {
    set.delete(tell);
    if (!set.size) watchers.delete(eventId);
    if (!watchers.size && timer) {
      clearInterval(timer);
      timer = null;
      stopSignal?.();
      stopSignal = null;
    }
  };
}

/** A lead call's state line. links: false in a row that is itself a link (Calls, Home). */
export function AutoCaptureState({
  eventId,
  links = true,
}: {
  eventId?: string | null;
  links?: boolean;
}) {
  const [shown, setShown] = useState<{
    id: string;
    track: Track | null;
  } | null>(null);
  useEffect(() => {
    if (!eventId) return;
    return watchCapture(eventId, (evidence) =>
      setShown({
        id: eventId,
        track: trackFor(evidence.native, evidence.server, evidence.unavailable),
      }),
    );
  }, [eventId]);
  const track = shown && eventId && shown.id === eventId ? shown.track : null;
  // In a list, a call with no evidence says nothing (an older app, or no capture here).
  if (!track || (!links && track.done < 0)) return null;
  return <CallTrack track={track} links={links} />;
}
