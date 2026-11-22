/**
 * The Outreach view's small words (v1.95): when, what, its delivery state.
 * Pure, so tests read them without a page.
 */
import type { TouchView } from "./outreach-client";

const TZ = "Asia/Kolkata";

/** Today's date in India, "2026-11-22" (the server's team day). */
export function teamDay(now = Date.now(), back = 0): string {
  const shifted = new Date(now + 330 * 60_000 - back * 86_400_000);
  return shifted.toISOString().slice(0, 10);
}

const CLOCK = new Intl.DateTimeFormat("en-IN", {
  timeZone: TZ,
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});
const DAY = new Intl.DateTimeFormat("en-IN", {
  timeZone: TZ,
  day: "numeric",
  month: "short",
});

/** "Today 11:02 am", "Yesterday 6:40 pm", "20 Nov, 10:15 am". */
export function whenWords(at: string, now = Date.now()): string {
  const day = teamDay(Date.parse(at));
  const clock = CLOCK.format(new Date(at)).replace(
    /\s?([AP]M)$/i,
    (_, m) => ` ${String(m).toLowerCase()}`,
  );
  if (day === teamDay(now)) return `Today ${clock}`;
  if (day === teamDay(now, 1)) return `Yesterday ${clock}`;
  return `${DAY.format(new Date(at))}, ${clock}`;
}

export const CHANNEL_NAMES: Record<string, string> = {
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
  call: "Call",
  messenger: "Messenger",
  instagram: "Instagram",
  in_person: "In person",
  other: "Other",
};

const STATUS_WORDS: Record<string, string> = {
  queued: "Waiting",
  opened: "Opened to send",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Failed",
  expired: "Not sent",
};

export const statusWords = (status: string) =>
  STATUS_WORDS[status] ??
  status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, " ");

/** What was sent, in one short line: the summary, the template or the file. */
export function whatWords(touch: TouchView): string {
  if (touch.summary) return touch.summary;
  if (touch.template_name) return `Template: ${touch.template_name}`;
  if (touch.attachment?.name) return touch.attachment.name;
  if (touch.channel === "call") return "Call";
  return `${CHANNEL_NAMES[touch.channel] ?? "Message"} message`;
}

/** Whether a touch went past a limit (the guard warned or held it). */
export const pastLimit = (touch: TouchView) =>
  touch.verdict !== "ok" || touch.after_block;

/** "Last 2 days ago" style, for a lead row: "2 days ago", "today". */
export function agoWords(at: string | null, now = Date.now()): string {
  if (!at) return "not yet";
  const days = Math.round(
    (Date.parse(teamDay(now)) - Date.parse(teamDay(Date.parse(at)))) /
      86_400_000,
  );
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}
