/**
 * Who goes through call capture setup, where, and which steps (owner, 30 Oct
 * 2026: "simple clicks and disclosure one by one, so that all our old as well as
 * new users have to agree"). Pure, so the gate decides without loading the flow.
 *
 * - An organisation's sellers must, on Home, Leads and Calls: until their name
 *   and phone are in, they agreed, and (in the phone app) this phone finished;
 *   or until they said no, which is asked again the next day.
 * - The phone app shows all five steps; the web shows the first two, then "open
 *   the app on your phone". An app too old to upload calls by itself is treated
 *   as the web, with "update the app".
 * - A personal workspace can't upload calls by itself, so it gets the same flow
 *   once in the phone app, every step skippable, without consent or uploads.
 * - Every phone is new: a fresh install has a new id and goes through it again.
 */

import { callIdFromPath } from "../analysis-routes";
import type { AutoCaptureStatus, SetupStatus } from "../leads/native-phone";
import type { CaptureSetup } from "./capture-setup-client";

/**
 * On the page while the setup is deciding or open, so "Set up this phone"
 * waits its turn (one flow, one screen at a time).
 */
export const CAPTURE_SETUP_ATTRIBUTE = "data-sx-capture-setup";

export type CaptureStep =
  | "profile"
  | "consent"
  | "recordings"
  | "background"
  | "uploads"
  /** The web's last step, or an app too old: finish on the phone. */
  | "phone"
  | "done";

/** What the phone app says about this phone, for the steps. */
export type PhoneFacts = Readonly<{
  device: string;
  model: string;
  family: string;
  version: string;
  /** This build can pick the folder and upload calls by itself. */
  captureSupported: boolean;
  folderPicked: boolean;
  /** The Phone app saves recordings, but its switch is off. */
  recorderOff: boolean;
  /** Google's Phone app: its recordings stay inside it. */
  privateDialler: boolean;
  battery: boolean;
  autostartNeeded: boolean;
  autostart: boolean;
  notifications: boolean;
  notificationsBlocked: boolean;
  uploadsOn: boolean;
  wifiOnly: boolean;
  /** Newest readable recording, when the phone says. */
  newestMs: number | null;
}>;

export function phoneFacts(
  setup: SetupStatus | null,
  capture: AutoCaptureStatus | null,
): PhoneFacts | null {
  if (!setup) return null;
  const recorder = setup.recorder;
  return {
    device: setup.device,
    model: setup.model,
    family: setup.family,
    version: setup.version,
    captureSupported:
      capture?.supported === true && setup.folderPickSupported === true,
    folderPicked: setup.folderPicked,
    recorderOff:
      recorder?.kind === "folder" &&
      recorder.recording === "off" &&
      setup.checks.recorder !== true,
    privateDialler: recorder?.kind === "private",
    battery: setup.checks.battery === true,
    autostartNeeded: setup.autostartNeeded,
    autostart: setup.checks.autostart === true,
    notifications: setup.checks.notifications === true,
    notificationsBlocked: setup.blocked.notifications,
    uploadsOn: capture?.on === true,
    wifiOnly: capture?.wifiOnly !== false,
    newestMs: recorder?.newestMs ?? null,
  };
}

const GATED = new Set([
  "/",
  "/dashboard",
  "/leads",
  "/leads/notes",
  "/calls",
  "/analysis",
  "/analysis/new",
  "/analysis/calls",
]);

/** Home, Leads and Calls (and their pages): where the setup is required. */
export function isGatedRoute(pathname: string | null): boolean {
  if (!pathname) return false;
  const route = pathname.replace(/\/$/, "") || "/";
  return (
    GATED.has(route) ||
    route.startsWith("/prospects/") ||
    route.startsWith("/leads/") ||
    callIdFromPath(route) !== null
  );
}

/** The seller said no (or turned it off) less than a day ago. */
export function noStillStands(setup: CaptureSetup, now: number): boolean {
  const again = setup.ask_again_at ? Date.parse(setup.ask_again_at) : NaN;
  return Number.isFinite(again) && now < again;
}

/** This phone finished before (an earlier run on this same install). */
export function phoneFinished(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
): boolean {
  return Boolean(
    phone?.device && setup.phones.some((item) => item.device === phone.device),
  );
}

/** Whether an organisation's seller must go through it before Home, Leads and Calls. */
export function setupRequired(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
  now: number,
): boolean {
  if (!setup.required || setup.workspace !== "organisation") return false;
  if (noStillStands(setup, now)) return false;
  if (!setup.profile_complete || setup.consent !== "on") return true;
  // The web, or an app too old to upload calls by itself: the first two steps are all.
  if (!phone?.captureSupported) return false;
  return !phoneFinished(setup, phone);
}

/** The steps, in order, for this workspace and this place. */
export function stepsFor(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
): CaptureStep[] {
  const personal = setup.workspace === "personal";
  const steps: CaptureStep[] = [];
  if (!setup.profile_complete) steps.push("profile");
  // Shown to everyone, even someone who agreed before: "all our old as well as
  // new users have to agree" (the agreed see their date and go on).
  steps.push("consent");
  if (!phone?.captureSupported) {
    if (!personal) steps.push("phone");
    return steps;
  }
  if (!phone.folderPicked || phone.recorderOff || phone.privateDialler)
    steps.push("recordings");
  if (!phone.battery || (phone.autostartNeeded && !phone.autostart))
    steps.push("background");
  if (!personal && (!phone.uploadsOn || !phone.notifications))
    steps.push("uploads");
  steps.push("done");
  return steps;
}

const PERSONAL_SEEN = (person: string, tenant: string) =>
  `sx-capture-setup:${person}:${tenant}`;

/** A personal workspace's flow shows once per phone. */
export function personalSeen(person: string, tenant: string): boolean {
  try {
    return window.localStorage.getItem(PERSONAL_SEEN(person, tenant)) !== null;
  } catch {
    // Without storage it is never offered: it is optional here.
    return true;
  }
}

export function markPersonalSeen(person: string, tenant: string) {
  try {
    window.localStorage.setItem(
      PERSONAL_SEEN(person, tenant),
      new Date().toISOString(),
    );
  } catch {
    // Nothing kept: it may show once more; it can be skipped.
  }
}

/** "a minute ago", "3 hours ago", "on 28 Oct": when the newest recording was saved. */
export function savedWhen(newestMs: number | null, now: number): string | null {
  if (!newestMs || newestMs > now) return null;
  const minutes = Math.floor((now - newestMs) / 60_000);
  if (minutes < 1) return "less than a minute ago";
  if (minutes < 60)
    return minutes === 1 ? "a minute ago" : `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  return `on ${new Date(newestMs).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "Asia/Kolkata",
  })}`;
}
