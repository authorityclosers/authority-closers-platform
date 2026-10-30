export type CaptureState =
  | "waiting"
  | "missing"
  | "uploaded"
  | "analysing"
  | "report_ready"
  | "short_call";
export type CaptureCall = {
  event_id: string;
  lead_id: string;
  person_id: string | null;
  at: string;
  state: CaptureState;
  submission_id: string | null;
  attention: boolean;
};
export type CaptureRate = {
  person_id: string;
  name: string;
  day: string;
  calls: number;
  received: number;
  analysed: number;
  rate: number;
  needs_fix: boolean;
};
export type CaptureGuard = {
  calls: CaptureCall[];
  rates: CaptureRate[];
  generated_at: string;
};
const inflight = new Map<string, Promise<CaptureGuard | null>>();
export function readCaptureGuard(
  eventId?: string,
): Promise<CaptureGuard | null> {
  const url = `/v1/lead-desk/capture-guard${eventId ? `?event_id=${encodeURIComponent(eventId)}` : ""}`;
  const existing = inflight.get(url);
  if (existing) return existing;
  const reading = fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  })
    .then(async (response) => {
      if (!response.ok) return null;
      const value = (await response.json()) as Partial<CaptureGuard>;
      return Array.isArray(value.calls) && Array.isArray(value.rates)
        ? (value as CaptureGuard)
        : null;
    })
    .catch(() => null)
    .finally(() => inflight.delete(url));
  inflight.set(url, reading);
  return reading;
}
