/**
 * The permissions checklist right after sign-in (owner, 30 Oct 2026, fix 5:
 * "call log, phone, contacts, notifications, and access to the recordings
 * folder ... the app cannot be used until all are granted"). Pure, so the gate
 * decides without loading its screen.
 *
 * In an organisation's workspace (owner, 3 Nov 2026) it is stricter: phone,
 * contacts, notifications and the recordings folder are needed to go on, at
 * every open and return, so a permission taken away later brings it back.
 * Call history, the battery and "Analyse my calls automatically" (the one-time
 * standing consent) are offered with Not now, and a put-off one stays as a slim
 * reminder. A personal workspace keeps the checklist it had.
 *
 * An item this build of the app can't ask for never locks anyone out: the
 * recordings folder on builds without the folder picker says "Update Sales
 * X-Ray"; contacts, which no released build declares yet (apps PR #18), isn't
 * shown until a build can ask (phone QA on v1.36, 3 Nov 2026: "Update" on the
 * newest build); call history in the Google Play build waits for Google's
 * approval and says so.
 */

import type { AutoAnalysisState } from "../settings/auto-analysis-client";
import type { SetupStatus } from "../leads/native-phone";

export type PermissionKey =
  | "callLog"
  | "phone"
  | "contacts"
  | "notifications"
  | "recordings"
  | "battery"
  | "autoAnalysis";

/**
 * granted: done (for the consent, it is on). needed: Android can still ask.
 * blocked: Android won't ask again, only its settings can. update: this app
 * build can't ask (a newer one can). later: not in this store's build yet.
 * elsewhere: only in an organisation's workspace (the phone refuses call
 * logging in Personal).
 */
export type PermissionState =
  | "granted"
  | "needed"
  | "blocked"
  | "update"
  | "later"
  | "elsewhere";

export type PermissionItem = Readonly<{
  key: PermissionKey;
  label: string;
  why: string;
  state: PermissionState;
  /** The app waits for it. */
  required: boolean;
  /** Offered with Not now (organisation workspaces): put off, it becomes a reminder. */
  canWait: boolean;
  /** The consent words' version: a new version asks again, even after Not now. */
  version?: string;
}>;

/**
 * The standing consent as the server has it (auto-analysis-client): "ask" is
 * a new notice version or new upload terms since the seller agreed. Null when
 * it couldn't be read: then the row isn't shown, and nothing waits on it.
 */
export type ConsentFact = Readonly<{
  state: AutoAnalysisState;
  /** The sealed words, shown as they are, never edited. */
  words: string;
  version: string;
}> | null;

/**
 * The battery's Done in the checklist, the seller's word that battery and
 * Autostart are set (HyperOS may not tell Android): kept on this phone, so
 * "Set up this phone" doesn't ask for them again (phone QA on v1.36, 3 Nov
 * 2026: Done, then Battery and Autostart with Skip for now, twice).
 */
const BATTERY_DONE_KEY = "sales-xray:battery-done";
export function batterySaidDone(): boolean {
  try {
    return window.localStorage.getItem(BATTERY_DONE_KEY) === "1";
  } catch {
    return false;
  }
}
export function sayBatteryDone(): void {
  try {
    window.localStorage.setItem(BATTERY_DONE_KEY, "1");
  } catch {
    // Storage off: the setup asks once more.
  }
}

/** On the page while the checklist decides or is open: the other first-run screens wait. */
export const PERMISSIONS_ATTRIBUTE = "data-sx-permissions";

/**
 * Whether the battery row holds the app. Not yet: HyperOS's "No restrictions"
 * may not reach Android's own check, and a row that can never turn green would
 * lock Xiaomi sellers out (asked of the orchestrator, 3 Nov 2026).
 */
export const BATTERY_REQUIRED = false;

/** Needed to go on in an organisation's workspace (owner, 3 Nov 2026). */
const REQUIRED: ReadonlySet<PermissionKey> = new Set<PermissionKey>([
  "phone",
  "contacts",
  "notifications",
  "recordings",
  ...(BATTERY_REQUIRED ? (["battery"] as const) : []),
]);

/**
 * In a personal workspace, asked for and never waited on: contacts
 * (orchestrator, 30 Oct 2026: "keep the web checklist line non-blocking").
 */
export const OPTIONAL: ReadonlySet<PermissionKey> = new Set(["contacts"]);

const has = (status: SetupStatus, key: string) =>
  Object.hasOwn(status.checks, key);

/** The rows, in the owner's order, for this phone, app build and workspace. */
export function permissionItems(
  status: SetupStatus,
  {
    organisation,
    consent = null,
  }: { organisation: boolean; consent?: ConsentFact },
): PermissionItem[] {
  const ask = (
    granted: boolean,
    blocked: boolean | undefined,
  ): PermissionState => (granted ? "granted" : blocked ? "blocked" : "needed");
  // The owner's four in an organisation's workspace; Personal waits as it did.
  const needs = (key: PermissionKey) =>
    organisation ? REQUIRED.has(key) : !OPTIONAL.has(key);
  const item = (
    value: Omit<PermissionItem, "required" | "canWait">,
  ): PermissionItem => ({
    ...value,
    required: needs(value.key),
    canWait: organisation && !REQUIRED.has(value.key),
  });
  const items = [
    item({
      key: "callLog",
      label: "Call log",
      why: "Logs your calls with leads on the lead. Other numbers stay on your phone.",
      state: !status.callLogSupported
        ? "later"
        : organisation
          ? ask(status.checks.callLog === true, false)
          : "elsewhere",
    }),
    item({
      key: "phone",
      label: "Phone",
      why: "Knows when a call starts and ends, so it is timed and its recording found.",
      state: ask(status.checks.calls === true, status.blocked.calls),
    }),
    item({
      key: "contacts",
      label: "Contacts",
      // The owner's purpose (30 Oct 2026): showing lead names on calls, nothing else.
      why: "Shows the right name on calls and leads by matching callers to your saved contacts. Read for nothing else.",
      state: ask(status.checks.contacts === true, status.blocked.contacts),
    }),
    item({
      key: "notifications",
      label: "Notifications",
      why: "New leads, calls that are due, and Undo before a call uploads.",
      state: ask(
        status.checks.notifications === true,
        status.blocked.notifications,
      ),
    }),
    item({
      key: "recordings",
      label: "Recordings folder",
      why: "Finds each call's recording in your Phone app's folder.",
      state: status.folderPickSupported
        ? status.folderPicked
          ? "granted"
          : "needed"
        : "update",
    }),
  ].filter((row) => row.key !== "contacts" || has(status, "contacts"));
  if (!organisation) return items;
  items.push(
    item({
      key: "battery",
      label: "Battery",
      why:
        status.family === "xiaomi"
          ? "Lets calls upload when the app is closed. Choose No restrictions, then allow Autostart for Sales X-Ray."
          : "Lets calls upload when the app is closed. Choose Unrestricted.",
      state: has(status, "battery")
        ? status.checks.battery === true
          ? "granted"
          : "needed"
        : "update",
    }),
  );
  if (consent && consent.state !== "unavailable")
    items.push(
      item({
        key: "autoAnalysis",
        label: "Analyse my calls automatically",
        why: consent.words,
        state: consent.state === "on" ? "granted" : "needed",
        version: consent.version,
      }),
    );
  return items;
}

const open = (item: PermissionItem) =>
  item.state === "needed" || item.state === "blocked";

/** Still to allow, and the app waits for it. */
export function waitsFor(item: PermissionItem): boolean {
  return item.required && open(item);
}

/** Anything this build can still grant that the app waits for. */
export function permissionsMissing(items: readonly PermissionItem[]): boolean {
  return items.some(waitsFor);
}

/** What Not now remembers: a new version of the consent words asks again. */
export function putOffKey(item: PermissionItem): string {
  return item.version ? `${item.key}:${item.version}` : item.key;
}

/** Still to answer here: what the app waits for, and what wasn't put off yet. */
export function toAnswer(
  items: readonly PermissionItem[],
  putOff: ReadonlySet<string>,
): PermissionItem[] {
  return items.filter(
    (item) =>
      waitsFor(item) ||
      (item.canWait && open(item) && !putOff.has(putOffKey(item))),
  );
}

/** The checklist opens while anything is still to answer. */
export function checklistOpen(
  items: readonly PermissionItem[],
  putOff: ReadonlySet<string>,
): boolean {
  return toAnswer(items, putOff).length > 0;
}

/**
 * Put off with Not now and still not done: the slim reminder names them. The
 * battery's Done is the seller's word that it is set, so it never reminds.
 */
export function reminders(
  items: readonly PermissionItem[],
  putOff: ReadonlySet<string>,
): PermissionItem[] {
  return items.filter(
    (item) =>
      item.canWait &&
      item.key !== "battery" &&
      open(item) &&
      putOff.has(putOffKey(item)),
  );
}
