/**
 * "Missed alert, come back" (owner, 17 Nov 2026): a new lead reached this
 * person's bell while this phone could not ring for it (Android's notification
 * permission is off), so the app says so the moment they open it and walks
 * them through setup, one step at a time. Pure, so the card decides without
 * loading its screen.
 */

import type { UpdateNotification } from "./updates-client";

/** A lead line this old is no news any more. */
export const MISSED_WINDOW_MS = 24 * 60 * 60 * 1000;

const LEAD_LINK = "/leads?lead=";

export type MissedLead = Readonly<{
  /** The bell line's id: the card never comes back for the same line. */
  lineId: string;
  leadId: string;
  name: string;
  /** "Meta ad · 7:42 PM": where it came from and when. */
  detail: string;
  href: string;
}>;

/** The lead's name from its bell line ("New lead: Asha", "Asha is your lead now"). */
export function leadName(line: UpdateNotification): string {
  return line.title
    .replace(/^New lead:\s*/, "")
    .replace(/\s+is your lead now$/, "")
    .trim();
}

/** Where it came from: the bell line's first part ("Meta ad", "New from Meta ad."). */
export function leadSource(line: UpdateNotification): string {
  const body = (line.body ?? "").trim();
  if (!body) return "";
  if (line.kind === "lead_new") return body.split(" · ")[0]?.trim() ?? "";
  const from = /^New from (.+?)\.(\s|$)/.exec(body);
  return from ? from[1].trim() : "";
}

/** "7:42 PM", as the phone's alert says it (India time). */
export function clockText(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: "Asia/Kolkata",
  })
    .format(at)
    .replace(/\s?(am|pm)$/i, (_, half: string) => ` ${half.toUpperCase()}`);
}

/**
 * The newest unread lead line from the last day that this person hasn't been
 * shown the card for, or null.
 */
export function missedLead(
  lines: readonly UpdateNotification[],
  now: number,
  shown: ReadonlySet<string>,
): MissedLead | null {
  const fresh = lines
    .filter(
      (line) =>
        (line.kind === "lead_new" || line.kind === "lead_assigned") &&
        !line.read &&
        typeof line.href === "string" &&
        line.href.startsWith(LEAD_LINK) &&
        !shown.has(line.id) &&
        now - Date.parse(line.created_at) <= MISSED_WINDOW_MS &&
        now - Date.parse(line.created_at) >= -60_000,
    )
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const line = fresh[0];
  if (!line?.href) return null;
  const leadId = line.href.slice(LEAD_LINK.length).split(/[&#]/)[0] ?? "";
  if (!leadId) return null;
  const detail = [leadSource(line), clockText(line.created_at)]
    .filter(Boolean)
    .join(" · ");
  return {
    lineId: line.id,
    leadId,
    name: leadName(line) || "A new lead",
    detail,
    href: line.href,
  };
}

export type SetupStep = "notifications" | "phone" | "audio" | "battery";

export const STEP_WORDS: Record<SetupStep, { title: string; why: string; button: string }> = {
  notifications: {
    title: "Notifications",
    why: "So new leads and due calls ring this phone.",
    button: "Allow notifications",
  },
  phone: {
    title: "Phone and call log",
    why: "So the calls you make are matched to the lead.",
    button: "Allow phone and calls",
  },
  audio: {
    title: "Music and audio",
    why: "So your call recordings can be found and analysed.",
    button: "Allow music and audio",
  },
  battery: {
    title: "Battery",
    why: "So alerts still arrive when the phone sleeps.",
    button: "Open battery settings",
  },
};

export type PhoneFacts = Readonly<{
  notifications: boolean;
  callAccess: boolean;
  audio: boolean;
  battery: boolean;
}>;

/** What this phone still needs, in the order the card asks for it. */
export function stepsLeft(facts: PhoneFacts): SetupStep[] {
  const steps: SetupStep[] = [];
  if (!facts.notifications) steps.push("notifications");
  if (!facts.callAccess) steps.push("phone");
  if (!facts.audio) steps.push("audio");
  if (!facts.battery) steps.push("battery");
  return steps;
}

/**
 * The card shows only when this phone could not have rung for the lead: its
 * notifications are off. (A phone that allows them registers by itself,
 * PushKeeper, 17 Nov 2026.)
 */
export function phoneMissedIt(facts: PhoneFacts | null): boolean {
  return facts !== null && !facts.notifications;
}

const SHOWN_KEY = (account: string) => `sales-xray:missed-alert-shown:${account}`;

/** The lines the card was already shown for on this phone (never nag twice). */
export function readShown(account: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(SHOWN_KEY(account));
    const list: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter((x) => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

export function markShown(account: string, lineId: string): void {
  try {
    const shown = [...readShown(account), lineId].slice(-50);
    window.localStorage.setItem(SHOWN_KEY(account), JSON.stringify(shown));
  } catch {
    // Without storage the card can come back once per app open; nothing worse.
  }
}
