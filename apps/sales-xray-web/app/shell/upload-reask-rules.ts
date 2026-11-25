/**
 * "Your call wasn't checked" (owner, 17 Nov 2026 app review: call upload and
 * auto-analysis are required; settle it in onboarding and ask again after a
 * call with no upload). When this phone saw a lead call end (its call log) and
 * no upload followed within ten minutes because uploads are off here, the app
 * names the call and turns uploads on step by step. Pure, so the card decides
 * without loading its screen. Shown once per call on this phone.
 */

import type { MissingCall } from "../capture-setup/capture-setup-client";
import type { AutoCaptureStatus } from "../leads/native-phone";
import { clockText } from "./missed-alert-rules";

/** No upload this long after the call ended: it isn't coming by itself. */
export const UPLOAD_WAIT_MS = 10 * 60 * 1000;
/** A call older than this is no news any more. */
export const UNCHECKED_WINDOW_MS = 24 * 60 * 60 * 1000;

export type UncheckedCall = Readonly<{
  eventId: string;
  leadId: string;
  name: string;
  /** "3:40 PM", India time, as the phone's own alerts say it. */
  clock: string;
  /** "2 min call · 3:40 PM". */
  detail: string;
  href: string;
  /** Every call this card covers: none of them asks again. */
  callIds: string[];
}>;

/** Uploads are off on this phone, by its own answer (a late answer says nothing). */
export function uploadsOffHere(status: AutoCaptureStatus | null): boolean {
  return (
    status !== null &&
    status.supported === true &&
    status.on === false &&
    status.unanswered !== true
  );
}

function ended(call: MissingCall): number {
  return Date.parse(call.at) + Math.max(0, call.seconds) * 1000;
}

function length(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec call`;
  return `${Math.round(seconds / 60)} min call`;
}

/**
 * The newest call that ended at least ten minutes ago with no recording, that
 * the card wasn't shown for on this phone; with every such call, so one card
 * covers them all. Null when there is none.
 */
export function uncheckedCall(
  calls: readonly MissingCall[],
  now: number,
  shown: ReadonlySet<string>,
): UncheckedCall | null {
  const due = calls
    .filter((call) => {
      const end = ended(call);
      return (
        Number.isFinite(end) &&
        !shown.has(call.event_id) &&
        now - end >= UPLOAD_WAIT_MS &&
        now - end <= UNCHECKED_WINDOW_MS
      );
    })
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  const call = due[0];
  if (!call) return null;
  const clock = clockText(call.at);
  return {
    eventId: call.event_id,
    leadId: call.lead_id,
    name: call.lead_name?.trim() || "your lead",
    clock,
    detail: [length(call.seconds), clock].filter(Boolean).join(" · "),
    href: `/leads?lead=${encodeURIComponent(call.lead_id)}`,
    callIds: due.map((item) => item.event_id),
  };
}

/** "Your call with Asha at 3:40 PM wasn't checked". */
export function headline(call: UncheckedCall): string {
  return call.clock
    ? `Your call with ${call.name} at ${call.clock} wasn't checked`
    : `Your call with ${call.name} wasn't checked`;
}

export type UploadStep = "notices" | "folder" | "uploads";

export const UPLOAD_STEP_WORDS: Record<
  UploadStep,
  { title: string; why: string; button: string }
> = {
  notices: {
    title: "Upload notices",
    why: "Each call shows a notice first, with 60 seconds to Undo before it uploads.",
    button: "Allow notices",
  },
  folder: {
    title: "Recordings folder",
    why: "So Sales X-Ray finds each call's recording on this phone.",
    button: "Choose the folder",
  },
  uploads: {
    title: "Uploads on",
    why: "Calls with your leads then upload by themselves and are analysed. Calls saved while uploads were off: you choose next whether to upload them too.",
    button: "Turn uploads on",
  },
};

export type UploadFacts = Readonly<{
  notifications: boolean;
  folderPicked: boolean;
}>;

/** What this phone still needs before uploads can go on, uploads last. */
export function uploadStepsLeft(facts: UploadFacts): UploadStep[] {
  const steps: UploadStep[] = [];
  if (!facts.notifications) steps.push("notices");
  if (!facts.folderPicked) steps.push("folder");
  steps.push("uploads");
  return steps;
}

const SHOWN_KEY = (account: string) =>
  `sales-xray:upload-reask-shown:${account}`;

/** The calls the card was already shown for on this phone (never nag twice). */
export function readShown(account: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(SHOWN_KEY(account));
    const list: unknown = raw ? JSON.parse(raw) : [];
    return new Set(
      Array.isArray(list) ? list.filter((x) => typeof x === "string") : [],
    );
  } catch {
    return new Set();
  }
}

export function markShown(account: string, callIds: readonly string[]): void {
  try {
    const shown = [...new Set([...readShown(account), ...callIds])].slice(-200);
    window.localStorage.setItem(SHOWN_KEY(account), JSON.stringify(shown));
  } catch {
    // Without storage the card can come back once per app open; nothing worse.
  }
}
