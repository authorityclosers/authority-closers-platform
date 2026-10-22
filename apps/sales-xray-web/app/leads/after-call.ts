/**
 * When a lead asks "How did it go?" (owner, 23 Oct 2026: "only after a real
 * call"). Only when a connected call is detected and not answered yet: the
 * phone app's own call that connected, or a call the phone logged from its own
 * dialler with talk time. Never after a WhatsApp or an email, a missed or
 * unanswered call, or a call whose end the page couldn't see (a browser hands
 * the number to the dialler and only knows the seller came back): those get a
 * light "Log this" chip instead, with a line saying what it is about.
 */

import type { LeadEvent } from "./leads-client";
import type { NativeCall } from "./native-phone";

/** A call or message older than this is not news: the chip says nothing of it. */
export const FRESH_MS = 12 * 60 * 60 * 1000;

export type AfterCall =
  /** Ask now; `heard` is what the phone saw, and fills in the answer. */
  | { ask: true; heard: NativeCall }
  /** The light chip; `hint` says what to log, when something just happened. */
  | { ask: false; hint: string | null; heard: NativeCall | null };

const MISSED: Partial<Record<NativeCall["result"], string>> = {
  no_answer: "nobody answered",
  busy: "the line was busy",
  rejected: "they cut the call",
  failed: "the call didn't go through",
  no_network: "the phone had no network",
};

const CHANNEL: Record<string, string> = {
  whatsapp: "on WhatsApp",
  sms: "by SMS",
  email: "by email",
};

const connected = (call: NativeCall) =>
  call.connected === true ||
  (call.connected === null && (call.durationSeconds ?? 0) > 0);

const time = (event: LeadEvent) => Date.parse(event.at) || 0;

/** The phone's own record of a dialler call, as the phone app would report it. */
function fromDialler(leadId: string, event: LeadEvent): NativeCall {
  return {
    leadId,
    number: "",
    startedMs: time(event),
    endedMs: null,
    durationSeconds: event.duration_seconds,
    connected: true,
    result: "answered",
    recording: null,
    final: true,
  };
}

export function afterCall({
  leadId,
  name,
  phoneCall,
  back,
  events,
  now = Date.now(),
}: {
  leadId: string;
  /** The lead's first name, for the chip's line. */
  name: string;
  /** The phone app's call to this lead, while its answer isn't saved. */
  phoneCall: NativeCall | null;
  /** Back from a browser's dialler: the call's end wasn't seen. */
  back: boolean;
  /** The lead's history, any order. */
  events: LeadEvent[];
  now?: number;
}): AfterCall {
  if (phoneCall && connected(phoneCall)) return { ask: true, heard: phoneCall };
  if (phoneCall)
    return {
      ask: false,
      heard: phoneCall,
      hint:
        phoneCall.connected === false
          ? `Your phone says ${MISSED[phoneCall.result] ?? "the call didn't connect"}.`
          : null,
    };
  // What happened last, and whether its answer is saved after it.
  const newest = [...events].sort((a, b) => time(b) - time(a));
  const answered = (event: LeadEvent) =>
    newest.some((item) => item.kind === "result" && time(item) >= time(event));
  const fresh = (event: LeadEvent) => now - time(event) <= FRESH_MS;
  const call = newest.find((event) => event.kind === "call");
  if (
    call &&
    call.via === "phone" &&
    (call.direction === "outgoing" || call.direction === "incoming") &&
    (call.duration_seconds ?? 0) > 0 &&
    fresh(call) &&
    !answered(call)
  )
    return { ask: true, heard: fromDialler(leadId, call) };
  if (back)
    return { ask: false, heard: null, hint: `Back from calling ${name}.` };
  const latest = newest.find(
    (event) => event.kind === "call" || event.kind === "message",
  );
  if (latest && fresh(latest) && !answered(latest)) {
    if (latest.kind === "message")
      return {
        ask: false,
        heard: null,
        hint:
          `You messaged ${name} ${CHANNEL[latest.channel ?? ""] ?? ""}`.trimEnd() +
          ".",
      };
    if (latest.via === "phone" && latest.direction === "missed")
      return {
        ask: false,
        heard: null,
        hint: `${name} called and nobody picked up.`,
      };
  }
  return { ask: false, heard: null, hint: null };
}
