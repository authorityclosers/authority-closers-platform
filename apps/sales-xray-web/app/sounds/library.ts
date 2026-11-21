/**
 * The sound library's Sales X-Ray part (brand kit sound/, library 0.1.0, 20 Nov
 * 2026): its moments, kinds and packs. Every sound the app plays comes from it;
 * nothing is made up in code (sound/AGENTS.md). The files are
 * public/sounds/<pack>/<kind>.mp3 with the library itself beside them
 * (public/sounds/library.json); library.test.ts holds this copy to it, and a
 * Python test holds the server's (lead_desk/sound_prefs.py).
 */

export const LIBRARY_VERSION = "0.1.0";

export type SoundKind =
  | "ringtone"
  | "message"
  | "mention"
  | "reminder"
  | "success"
  | "error";

export type SoundCategory = "calls" | "messages" | "reminders" | "feedback";

export type SxEventId =
  | "sx.incoming_call"
  | "sx.new_lead"
  | "sx.new_message"
  | "sx.follow_up_due"
  | "sx.report_ready"
  | "sx.upload_failed";

export type SoundEvent = {
  id: SxEventId;
  label: string;
  kind: SoundKind;
  /** The library's sound id when nobody picked one. */
  default: string;
};

export const CATEGORIES: readonly { id: SoundCategory; label: string }[] = [
  { id: "calls", label: "Calls" },
  { id: "messages", label: "Messages & leads" },
  { id: "reminders", label: "Reminders" },
  { id: "feedback", label: "Feedback" },
];

export const KINDS: Record<
  SoundKind,
  { label: string; category: SoundCategory }
> = {
  ringtone: { label: "Ringtone", category: "calls" },
  message: { label: "Message", category: "messages" },
  mention: { label: "Mention", category: "messages" },
  reminder: { label: "Reminder", category: "reminders" },
  success: { label: "Success", category: "feedback" },
  error: { label: "Error", category: "feedback" },
};

export const SX_EVENTS: readonly SoundEvent[] = [
  {
    id: "sx.incoming_call",
    label: "Incoming call",
    kind: "ringtone",
    default: "glass-v3.ringtone",
  },
  {
    id: "sx.new_lead",
    label: "New lead given to me",
    kind: "mention",
    default: "glass-v2.mention",
  },
  {
    id: "sx.new_message",
    label: "New message / update",
    kind: "message",
    default: "glass-v2.message",
  },
  {
    id: "sx.follow_up_due",
    label: "Follow-up due",
    kind: "reminder",
    default: "glass-v2.reminder",
  },
  {
    id: "sx.report_ready",
    label: "Call report ready",
    kind: "success",
    default: "glass-v1.success",
  },
  {
    id: "sx.upload_failed",
    label: "Recording/upload problem",
    kind: "error",
    default: "glass-v3.error",
  },
];

export type PackFamily = "glass" | "warm" | "pulse" | "synth";

export type SoundPack = { id: string; title: string; family: PackFamily };

/** In the order the picker shows them: the recommended Glass first. */
export const PACKS: readonly SoundPack[] = [
  { id: "glass-v1", title: "Glass V1", family: "glass" },
  { id: "glass-v2", title: "Glass V2", family: "glass" },
  { id: "glass-v3", title: "Glass V3", family: "glass" },
  { id: "warm-v1", title: "Warm V1", family: "warm" },
  { id: "warm-v2", title: "Warm V2", family: "warm" },
  { id: "warm-v3", title: "Warm V3", family: "warm" },
  { id: "pulse-v1", title: "Pulse V1", family: "pulse" },
  { id: "pulse-v2", title: "Pulse V2", family: "pulse" },
  { id: "pulse-v3", title: "Pulse V3", family: "pulse" },
  { id: "A", title: "Synth A", family: "synth" },
  { id: "B", title: "Synth B", family: "synth" },
  { id: "C", title: "Synth C", family: "synth" },
];

export const FAMILIES: readonly { id: PackFamily; label: string }[] = [
  { id: "glass", label: "Glass" },
  { id: "warm", label: "Warm" },
  { id: "pulse", label: "Pulse" },
  { id: "synth", label: "Synth" },
];
