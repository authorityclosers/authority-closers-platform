/**
 * Words for the phone setup checklist (UX study item 7): one line per thing
 * the phone needs, an explainer for each permission before Android asks
 * (TeleCRM and Callyzer show one), the call recorder steps for each brand,
 * and the dot a manager sees for each seller's phone on Team.
 */

import { ago, type PhoneHealth } from "./leads-client";

export type PhoneCheck =
  | "calls"
  | "recordings"
  | "notifications"
  | "recorder"
  | "folder"
  | "battery"
  | "autostart"
  | "testCall"
  | "callLog";

export const CHECK_ORDER: PhoneCheck[] = [
  "calls",
  "recordings",
  "notifications",
  "recorder",
  "folder",
  "battery",
  "autostart",
  "testCall",
  "callLog",
];

export const CHECK_LABELS: Record<PhoneCheck, string> = {
  calls: "Calls and call history",
  recordings: "Call recordings",
  notifications: "Notifications",
  recorder: "Call recorder on",
  folder: "Recordings folder found",
  battery: "Battery unrestricted",
  autostart: "Autostart allowed",
  testCall: "Test call recorded",
  callLog: "Work calls logged",
};

/** What a line says while it is not done yet. */
export const CHECK_TODO: Record<PhoneCheck, string> = {
  calls: "Call a lead in one tap and log the call by itself.",
  recordings: "Find the recording of a call to analyse it.",
  notifications: "Hear about a new lead or a call that is due.",
  recorder: "Your phone's dialer saves every call.",
  folder: "Ticks when your phone's first call recording appears.",
  battery: "Your phone lets Sales Xray run in the background.",
  autostart: "Your phone lets Sales Xray start by itself.",
  testCall:
    "Call any lead from Sales Xray and talk for a few seconds. Ticks when the recording is found.",
  callLog: "Calls with your leads from the phone dialer show on the lead.",
};

export type Explainer = {
  title: string;
  reads: string;
  sends: string;
  why: string;
  allow: string;
};

/** One screen per permission, shown before Android asks. */
export const EXPLAINERS: Partial<Record<PhoneCheck, Explainer>> = {
  calls: {
    title: "Calls and call history",
    reads:
      "When you call a lead from Sales Xray, the app places the call and reads how long it lasted from your call history.",
    sends:
      "Only calls with your leads: when they happened and how long they lasted. Other numbers never leave your phone.",
    why: "So every call is logged and the after-call answer is filled in for you.",
    allow: "Allow calls",
  },
  recordings: {
    title: "Call recordings",
    reads:
      "The call recordings your phone's own dialer saves, so the app can find the one for a call.",
    sends:
      "Only a recording you choose to analyse, after you agree to the terms. Nothing is sent by itself.",
    why: "So a call can get its Report with the AI's notes.",
    allow: "Allow recordings",
  },
  notifications: {
    title: "Notifications",
    reads: "Nothing. Sales Xray only shows you alerts.",
    sends: "Nothing.",
    why: "So you hear about a new lead the moment it comes in, and about a call that is due.",
    allow: "Allow notifications",
  },
  battery: {
    title: "Battery unrestricted",
    reads: "Nothing.",
    sends: "Nothing.",
    why: "Android stops apps in the background to save battery. Sales Xray needs to wake up now and then to log your calls and show alerts. It uses very little battery.",
    allow: "Open battery settings",
  },
};

/** "Record calls automatically" in each brand's own dialer. */
export const RECORDER_STEPS: Record<string, string[]> = {
  xiaomi: [
    "Open the Phone app.",
    "Tap ⋮ at the top, then Settings.",
    "Tap Call recording.",
    "Turn on Record calls automatically, for All numbers.",
  ],
  samsung: [
    "Open the Phone app.",
    "Tap ⋮ at the top, then Settings.",
    "Tap Record calls.",
    "Turn on Auto record calls, for All calls.",
  ],
  vivo: [
    "Open the Phone app.",
    "Tap ⋮ or Settings, then Call recording.",
    "Turn on Auto record calls, for All calls.",
  ],
  oppo: [
    "Open the Phone app.",
    "Tap ⋮ at the top, then Settings.",
    "Tap Call recording.",
    "Turn on Auto-record calls, for All calls.",
  ],
  realme: [
    "Open the Phone app.",
    "Tap ⋮ at the top, then Settings.",
    "Tap Call recording.",
    "Turn on Auto-record calls, for All calls.",
  ],
  oneplus: [
    "Open the Phone app.",
    "Tap ⋮ at the top, then Settings.",
    "Tap Call recording.",
    "Turn on Auto-record calls, for All calls.",
  ],
  huawei: [
    "Open the Phone app.",
    "Tap ⋮ at the top, then Settings.",
    "Turn on Auto-record calls.",
  ],
  other: [
    "Open your phone's dialer and look in its settings for Call recording.",
    "Turn on automatic recording for all calls, if your phone has it.",
    "Google's Phone app keeps its recordings private, so Sales Xray can't read them.",
  ],
};

export function recorderSteps(family: string): string[] {
  return RECORDER_STEPS[family] ?? RECORDER_STEPS.other;
}

export type PhoneDot = {
  tone: "good" | "warn" | "bad" | "none";
  label: string;
  /** The lines still to do, in plain words. */
  missing: string[];
};

const HOUR = 60 * 60 * 1000;

/** One dot and a few words for a seller's phone on Team (Salestrail's dots). */
export function phoneDot(
  phone: PhoneHealth | null | undefined,
  now: Date = new Date(),
): PhoneDot {
  if (!phone) return { tone: "none", label: "No phone app", missing: [] };
  const missing = CHECK_ORDER.filter((key) => phone.checks[key] === false).map(
    (key) => CHECK_LABELS[key],
  );
  const age = (iso: string) => now.getTime() - new Date(iso).getTime();
  // Logging is on, but the phone hasn't looked at its call history for a while.
  if (phone.call_log_on && phone.synced_at && age(phone.synced_at) > 3 * HOUR)
    return {
      tone: "bad",
      label: `Last call check ${ago(phone.synced_at, now)}`,
      missing,
    };
  if (age(phone.reported_at) > 72 * HOUR)
    return {
      tone: "bad",
      label: `App last open ${ago(phone.reported_at, now)}`,
      missing,
    };
  if (!missing.length) return { tone: "good", label: "Ready", missing };
  return {
    tone: "warn",
    label: `${phone.done} of ${phone.total} set up`,
    missing,
  };
}
