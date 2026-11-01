/**
 * Each person's own notification choices (competitor teardown 26, 1 Nov
 * 2026): /v1/lead-desk/notifications, anyone in the workspace for themselves.
 */

export type DueLead = 0 | 15 | 60;

export type NotifyPrefs = {
  new_enquiry: boolean;
  follow_up_due: boolean;
  missed_follow_up: boolean;
  team_alerts: boolean;
  /** A follow-up's alert: at the time, 15 minutes or an hour before. */
  due_lead_minutes: DueLead;
  /** Quiet outside the team's working hours. */
  quiet: boolean;
  /** "10:30–7:00, Mon–Sat", or null when the team has none. */
  working_hours: string | null;
  /** Owners and admins also choose team alerts and the day's summary. */
  manager: boolean;
  phones: number;
};

export type NotifyTest = { phones: number; sent: number; ready: boolean };

export class NotifyError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const BASE = "/v1/lead-desk/notifications";

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = "That didn’t work. Try again.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The plain words stay.
    }
    throw new NotifyError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const readNotify = (signal?: AbortSignal) =>
  call<NotifyPrefs>("", { signal });

export const saveNotify = (
  next: Pick<
    NotifyPrefs,
    | "new_enquiry"
    | "follow_up_due"
    | "missed_follow_up"
    | "team_alerts"
    | "due_lead_minutes"
    | "quiet"
  >,
) => call<NotifyPrefs>("", { method: "PUT", body: JSON.stringify(next) });

export const testNotify = () => call<NotifyTest>("/test", { method: "POST" });

/**
 * What to do when no phone of this person gets alerts yet. Inside the phone
 * app that means this phone's notifications, never "sign in on your phone"
 * (phone personas ph1-57, 1 Nov 2026: the app said so to someone in it).
 */
export function noPhoneWords(inApp: boolean): string {
  return inApp
    ? "This phone isn't getting alerts yet. Allow notifications for Sales X-Ray on it, then try again."
    : "Alerts reach the Sales X-Ray app. Sign in to it on your phone to get them.";
}
