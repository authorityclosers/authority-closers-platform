/**
 * Owner alerts and the day's summary (competitor teardown 19 and 20, 1 Nov
 * 2026): /v1/lead-desk/owner-alerts, owners and admins only. The server sends
 * them; these read and save the switches, open an alert's list and today's
 * summary, and send a test summary to the owner's own phone.
 */

export type AlertKind =
  | "first_call"
  | "missed_call"
  | "no_follow_up"
  | "seller_idle";
export const ALERT_KINDS: readonly AlertKind[] = [
  "first_call",
  "missed_call",
  "no_follow_up",
  "seller_idle",
];

export type OwnerAlerts = {
  first_call: boolean;
  missed_call: boolean;
  no_follow_up: boolean;
  seller_idle: boolean;
  first_call_minutes: number;
  /** The first-call target already alerts managers: its switch is that one. */
  first_call_by_target: boolean;
  /** Idle sellers count inside working hours only. */
  work_hours: boolean;
  /** This person's summary days, 0 for Monday; empty is off. */
  summary_days: number[];
  /** This person's phones with the app. */
  phones: number;
};

export type AlertItem = {
  lead_id: string | null;
  person_id: string | null;
  name: string;
  seller: string | null;
  since: string;
};
export type AlertList = {
  kind: AlertKind;
  title: string;
  items: AlertItem[];
  more: number;
};

export type SummarySeller = {
  person_id: string;
  name: string;
  tried: number;
  connected: number;
  talk_seconds: number;
  follow_ups_done: number;
  wins: number;
  no_recording: number;
};
export type DaySummary = {
  day: string;
  sellers: SummarySeller[];
  totals: { sellers: number; tried: number; connected: number; wins: number };
};

export type TestSent = { phones: number; sent: number; ready: boolean };

export class OwnerAlertsError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const BASE = "/v1/lead-desk/owner-alerts";

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
      // No words from the server: the plain ones stay.
    }
    throw new OwnerAlertsError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const readOwnerAlerts = (signal?: AbortSignal) =>
  call<OwnerAlerts>("", { signal });

export const saveOwnerAlerts = (
  next: Pick<
    OwnerAlerts,
    | "first_call"
    | "missed_call"
    | "no_follow_up"
    | "seller_idle"
    | "summary_days"
  >,
) => call<OwnerAlerts>("", { method: "PUT", body: JSON.stringify(next) });

export const readAlertList = (kind: AlertKind, signal?: AbortSignal) =>
  call<AlertList>(`/list?kind=${kind}`, { signal });

export const readDaySummary = (signal?: AbortSignal) =>
  call<DaySummary>("/summary", { signal });

export const sendTestSummary = () =>
  call<TestSent>("/summary/test", { method: "POST" });

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** "7 PM · Every day", "7 PM · Mon–Sat", "7 PM · Mon, Wed", or "Off". */
export function summaryWhen(days: readonly number[]): string {
  const picked = [...new Set(days)].filter((day) => day >= 0 && day <= 6);
  picked.sort((a, b) => a - b);
  if (!picked.length) return "Off";
  if (picked.length === 7) return "7 PM · Every day";
  const run = picked.every((day, index) => day === picked[0] + index);
  if (run && picked.length >= 3)
    return `7 PM · ${DAYS[picked[0]]}–${DAYS[picked[picked.length - 1]]}`;
  return `7 PM · ${picked.map((day) => DAYS[day]).join(", ")}`;
}

/** The alerts that will reach an owner now, of the four. */
export function alertsOn(
  view: OwnerAlerts,
  target: { on: boolean; alertManagers: boolean } | null,
): number {
  const first = target?.on ? target.alertManagers : view.first_call;
  return [
    first,
    view.missed_call,
    view.no_follow_up,
    view.seller_idle && view.work_hours,
  ].filter(Boolean).length;
}
