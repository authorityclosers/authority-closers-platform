"use client";

/**
 * "4 calls today have no recording · Fix" (competitor teardown #13, 1 Nov
 * 2026): one line at the top of Calls and Reports, never a card floating over
 * a call or the follow-ups, and never on Home, whose Tried row already carries
 * the count. Owner, 30 Oct 2026 (fix 5): a connected call with no recording
 * two minutes after it ended tells the seller how to fix it.
 *
 * The server counts the seller's own connected lead calls with no recording,
 * from the same calls Home counts as Tried (call_ai/missing_recordings.py), so
 * it never shows beside "Tried 0". The count opens the calls themselves; Fix
 * opens the setup at the step that fails on this phone (capture-setup-rules.ts
 * failingStep).
 *
 * The bell's reminder opens Calls at its own day, ?no-recording=2026-10-30
 * (phone personas ph1-27, 1 Nov 2026: its See why did nothing): the line then
 * names that day, as the bell does, with its calls listed.
 *
 * While "Analyse my calls automatically" is still to choose, the line once a
 * day says what that costs instead (owner, 3 Nov 2026): "3 calls today could
 * have had a coaching report · Turn on · Not now". With uploads off those are
 * the same calls, still on the phone. Turn on opens the checklist's consent
 * row with its sealed words (Settings on the web); Not now keeps it away a
 * week (leads/auto-start.ts).
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  AUTO_ANALYSIS_SETTINGS_HREF,
  markNudged,
  notNow,
  nudgeDue,
} from "../leads/auto-start";
import {
  autoCaptureStatus,
  inPhoneApp,
  onPhoneSignal,
  setupStatus,
} from "../leads/native-phone";
import {
  readAutoAnalysis,
  type AutoAnalysis,
} from "../settings/auto-analysis-client";
import { useWorkspaceAccess } from "../workspace-access";
import {
  readMissingRecordings,
  type MissingRecordings,
} from "./capture-setup-client";
import { openCaptureSetup } from "./capture-setup-gate";
import { failingStep, phoneFacts } from "./capture-setup-rules";
import own from "./capture-setup.module.css";
import { askConsent } from "./permissions-gate";

const EVERY_MS = 120_000;
/** The bell's reminder: Calls, at that day's calls without a recording. */
export const DAY_PARAM = "no-recording";

/** Today in India, the day the server counts. */
function today(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

/** The day the bell's reminder asked for, when it isn't today. */
function askedDay(): string | null {
  if (typeof window === "undefined") return null;
  const day = new URLSearchParams(window.location.search).get(DAY_PARAM);
  return day && /^\d{4}-\d{2}-\d{2}$/.test(day) && day !== today() ? day : null;
}

/** "30 Oct", as the bell names the day. */
function dayName(day: string): string {
  return new Date(`${day}T12:00:00+05:30`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "Asia/Kolkata",
  });
}

/** "4 calls today have no recording", or the bell's "30 Oct: 4 calls had no recording". */
export function missingWords(calls: number, day: string | null): string {
  const what = calls === 1 ? "1 call" : `${calls} calls`;
  if (day) return `${dayName(day)}: ${what} had no recording`;
  return `${what} today ${calls === 1 ? "has" : "have"} no recording`;
}

const clock = (at: string) =>
  new Date(at).toLocaleTimeString("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });

const talk = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

/** "3 calls today could have had a coaching report" (owner, 3 Nov 2026). */
export function nudgeWords(calls: number): string {
  return `${calls === 1 ? "1 call" : `${calls} calls`} today could have had a coaching report`;
}

/** The day's gentle ask, in the line's place: Turn on, or Not now for a week. */
export function ConsentNudge({
  calls,
  onTurnOn,
  onNotNow,
}: {
  calls: number;
  onTurnOn: () => void;
  onNotNow: () => void;
}) {
  return (
    <section className={own.missingLine} aria-label="Automatic analysis">
      <p>
        <span>{nudgeWords(calls)}</span>
        <span aria-hidden="true">·</span>
        {inPhoneApp() ? (
          <button type="button" data-fix="" onClick={onTurnOn}>
            Turn on
          </button>
        ) : (
          <Link href={AUTO_ANALYSIS_SETTINGS_HREF} onClick={onTurnOn}>
            Turn on
          </Link>
        )}
        <span aria-hidden="true">·</span>
        <button type="button" onClick={onNotNow}>
          Not now
        </button>
      </p>
    </section>
  );
}

/** Fix: the setup, at the step that fails on this phone; on the web, "open the app". */
export async function fixRecording() {
  const [status, capture] = inPhoneApp()
    ? await Promise.all([setupStatus(), autoCaptureStatus()])
    : [null, null];
  openCaptureSetup(failingStep(phoneFacts(status, capture)));
}

/** The line: the count opens the calls themselves, Fix the step that fails. */
export function MissingLine({
  missing,
  day = null,
  onFix = fixRecording,
}: {
  missing: MissingRecordings;
  /** A past day the bell's reminder asked for: named, its calls listed. */
  day?: string | null;
  onFix?: () => void | Promise<void>;
}) {
  const [open, setOpen] = useState(day !== null);
  // The bell's day, after its recordings arrived: say so, never a dead end.
  if (day && missing.calls === 0)
    return (
      <section className={own.missingLine} data-state="fine">
        <p role="status">{dayName(day)}: every call has its recording now</p>
      </section>
    );
  // Today's line agrees with Home: nothing when nothing was tried.
  if (missing.calls === 0 || (!day && missing.tried === 0)) return null;
  return (
    <section className={own.missingLine} aria-label="Calls without a recording">
      <p>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {missingWords(missing.calls, day)}
        </button>
        <span aria-hidden="true">·</span>
        <button type="button" data-fix="" onClick={() => void onFix()}>
          Fix
        </button>
      </p>
      {open && missing.items.length ? (
        <ul>
          {missing.items.map((item) => (
            <li key={item.event_id}>
              <Link href={`/leads?lead=${encodeURIComponent(item.lead_id)}`}>
                {item.lead_name ?? "A lead"}
              </Link>
              <small>
                {clock(item.at)} · {talk(item.seconds)}
              </small>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** Calls and Reports: the seller's own calls without a recording, today or the bell's day. */
export function RecordingLine() {
  const access = useWorkspaceAccess();
  const ready =
    access?.authenticated === true &&
    access.status === "ready" &&
    access.context !== null;
  const [day] = useState(askedDay);
  const [missing, setMissing] = useState<MissingRecordings | null>(null);
  // Read only once the line has calls to name; the ask is decided once a visit.
  const [consent, setConsent] = useState<AutoAnalysis | null>(null);
  const [nudge, setNudge] = useState<boolean | null>(null);
  const counted =
    !day && missing !== null && missing.calls > 0 && missing.tried > 0;

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    const read = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        setMissing(
          await readMissingRecordings(controller.signal, day ?? undefined),
        );
      } catch {
        // A failed read shows nothing; the next one tries again.
      }
    };
    void read();
    const timer = window.setInterval(() => void read(), EVERY_MS);
    const stop = onPhoneSignal((event) => {
      if (event === "resume") void read();
    });
    return () => {
      controller.abort();
      window.clearInterval(timer);
      stop();
    };
  }, [ready, day]);

  useEffect(() => {
    if (!counted || consent) return;
    const controller = new AbortController();
    readAutoAnalysis(controller.signal).then(
      (view) => {
        // Decided once a visit: the day's one ask, never again today.
        const due = nudgeDue(view);
        if (due) markNudged();
        setConsent(view);
        setNudge(due);
      },
      () => setNudge(false),
    );
    return () => controller.abort();
  }, [counted, consent]);

  if (missing && counted && nudge)
    return (
      <ConsentNudge
        calls={missing.calls}
        onTurnOn={() => {
          if (inPhoneApp()) askConsent();
          setNudge(false);
        }}
        onNotNow={() => {
          notNow();
          setNudge(false);
        }}
      />
    );
  return missing ? <MissingLine missing={missing} day={day} /> : null;
}
