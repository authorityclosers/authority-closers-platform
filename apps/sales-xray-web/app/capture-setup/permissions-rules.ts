/**
 * The permissions checklist right after sign-in (owner, 30 Oct 2026, fix 5:
 * "call log, phone, contacts, notifications, and access to the recordings
 * folder ... the app cannot be used until all are granted"). Pure, so the gate
 * decides without loading its screen.
 *
 * An item this build of the app can't ask for never locks anyone out: contacts
 * on builds that don't declare them, and the recordings folder on builds without
 * the folder picker, say "Update Sales X-Ray"; call history in the Google Play
 * build waits for Google's approval and says so.
 */

import type { SetupStatus } from "../leads/native-phone";

export type PermissionKey =
  | "callLog"
  | "phone"
  | "contacts"
  | "notifications"
  | "recordings";

/**
 * granted: done. needed: Android can still ask. blocked: Android won't ask
 * again, only its settings can. update: this app build can't ask (a newer one
 * can). later: not in this store's build yet. elsewhere: only in an
 * organisation's workspace (the phone refuses call logging in Personal).
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
}>;

/** On the page while the checklist decides or is open: the other first-run screens wait. */
export const PERMISSIONS_ATTRIBUTE = "data-sx-permissions";

const has = (status: SetupStatus, key: string) =>
  Object.hasOwn(status.checks, key);

/** The five items, in the owner's order, for this phone, app build and workspace. */
export function permissionItems(
  status: SetupStatus,
  { organisation }: { organisation: boolean },
): PermissionItem[] {
  const ask = (
    granted: boolean,
    blocked: boolean | undefined,
  ): PermissionState => (granted ? "granted" : blocked ? "blocked" : "needed");
  return [
    {
      key: "callLog",
      label: "Call log",
      why: "Logs your calls with leads on the lead. Other numbers stay on your phone.",
      state: !status.callLogSupported
        ? "later"
        : organisation
          ? ask(status.checks.callLog === true, false)
          : "elsewhere",
    },
    {
      key: "phone",
      label: "Phone",
      why: "Knows when a call starts and ends, so it is timed and its recording found.",
      state: ask(status.checks.calls === true, status.blocked.calls),
    },
    {
      key: "contacts",
      label: "Contacts",
      // The owner's purpose (30 Oct 2026): showing lead names on calls, nothing else.
      why: "Shows the right name on calls and leads by matching callers to your saved contacts. Read for nothing else.",
      state: has(status, "contacts")
        ? ask(status.checks.contacts === true, status.blocked.contacts)
        : "update",
    },
    {
      key: "notifications",
      label: "Notifications",
      why: "New leads, calls that are due, and Undo before a call uploads.",
      state: ask(
        status.checks.notifications === true,
        status.blocked.notifications,
      ),
    },
    {
      key: "recordings",
      label: "Recordings folder",
      why: "Finds each call's recording in your Phone app's folder.",
      state: status.folderPickSupported
        ? status.folderPicked
          ? "granted"
          : "needed"
        : "update",
    },
  ];
}

/**
 * Asked for, never waited on: contacts (orchestrator, 30 Oct 2026: "keep the
 * web checklist line non-blocking"). Their purpose is set (lead names on
 * calls), but no build reads them yet.
 */
export const OPTIONAL: ReadonlySet<PermissionKey> = new Set(["contacts"]);

/** Still to allow, and the app waits for it. */
export function waitsFor(item: PermissionItem): boolean {
  return (
    !OPTIONAL.has(item.key) &&
    (item.state === "needed" || item.state === "blocked")
  );
}

/** Anything this build can still grant: the app waits until it is. */
export function permissionsMissing(items: readonly PermissionItem[]): boolean {
  return items.some(waitsFor);
}
