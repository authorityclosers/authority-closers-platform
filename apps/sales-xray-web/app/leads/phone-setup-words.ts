/**
 * Words for the phone setup checklist (UX study item 7): one line per thing
 * the phone needs, an explainer for each permission before Android asks
 * (TeleCRM and Callyzer show one), the call recorder steps for each brand,
 * and the dot a manager sees for each seller's phone on Team.
 */

import type { RecorderProfile } from "./native-phone";
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

/**
 * Xiaomi, Redmi and POCO keep call recordings in a folder other apps can't see
 * (Redmi audit #49): Android shows it to Sales Xray only with All files access.
 */
export const ALL_FILES_EXPLAINER: Explainer = {
  title: "Call recordings",
  reads:
    "Only your Phone app's call recordings folder. Sales Xray doesn't open your photos, documents or other files.",
  sends:
    "Only a recording you choose to analyse, after you agree to the terms. Nothing is sent by itself.",
  why: "Your phone keeps call recordings in a hidden folder. Android lets Sales Xray see it only with All files access. Turn it on for Sales Xray, then come back.",
  allow: "Open All files access",
};

/** The line under Call recordings while the folder is hidden. */
export const HIDDEN_TODO =
  "Your phone hides its call recordings. Allow All files access.";

/** Truecaller's after-call screen covers "How did it go?" (Redmi audit #48). */
export const TRUECALLER_NOTE =
  "Truecaller opens its own screen after each call, on top of Sales Xray. Close it to log your call, or tap the How did the call go? notification.";

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

export type RecorderGuide = {
  /** One line on what the phone does now, or null when the app can't tell. */
  lead: string | null;
  steps: string[];
  /** Google's Phone app: no app can read its recordings, so "It's on" means nothing. */
  closed: boolean;
};

/** The recorder steps for this phone, from what the app found on it. */
export function recorderGuide(
  recorder: RecorderProfile | null,
  family: string,
): RecorderGuide {
  if (!recorder)
    return { lead: null, steps: recorderSteps(family), closed: false };
  if (recorder.kind === "private") {
    return {
      lead: `${recorder.dialerLabel} is Google's Phone app. It keeps call recordings inside itself, so no other app, Sales Xray included, can read them.`,
      steps: recorder.switchTo
        ? [
            `Make ${recorder.switchTo} your Phone app (Settings, Apps, Default apps, Phone app).`,
            `Open ${recorder.switchTo}, then its Settings, and turn on Call recording for all calls.`,
            "Or record meetings in Sales Xray: Calls on this phone, then Record.",
          ]
        : [
            "This phone has no other Phone app that saves recordings.",
            "Record meetings and in-person talks in Sales Xray: Calls on this phone, then Record.",
            "Phone calls can be recorded only by phones whose own Phone app saves them (Samsung, Xiaomi's own dialer, OnePlus, Oppo, Realme, Vivo).",
          ],
      closed: true,
    };
  }
  const found = recorder.folders.find((row) => row.state === "found");
  const where = found ?? recorder.folders[0];
  if (where?.state === "hidden")
    return {
      lead: `${recorder.dialerLabel} saves recordings in ${where.path}, which your phone hides from other apps. Allow All files access for Sales Xray in Call recordings.`,
      steps: recorderSteps(family),
      closed: false,
    };
  const lead =
    recorder.recording === "on"
      ? found
        ? `${recorder.dialerLabel} records your calls. ${found.recordings} found in ${found.path}.`
        : `${recorder.dialerLabel} records your calls.`
      : recorder.recording === "off"
        ? `Call recording is off in ${recorder.dialerLabel}.`
        : where
          ? `No call recordings yet in ${where.path}.`
          : null;
  return { lead, steps: recorderSteps(family), closed: false };
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
