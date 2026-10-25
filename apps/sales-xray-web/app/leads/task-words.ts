/**
 * Tasks in a seller's words (work-memory engine, docs/product/lead-desk/
 * work-memory-engine.md): what each kind is called, when one is due, and the
 * quick times Remind offers. Times are the phone's own (India for our sellers).
 */

import {
  CalendarClock,
  CircleDot,
  Mail,
  MessageCircle,
  Paperclip,
  Phone,
  type LucideIcon,
} from "lucide-react";

import type { TaskBucket, TaskKind, TaskView } from "./leads-client";

export const TASK_KINDS: { key: TaskKind; label: string; icon: LucideIcon }[] =
  [
    { key: "call_back", label: "Call back", icon: Phone },
    { key: "whatsapp", label: "WhatsApp", icon: MessageCircle },
    { key: "email", label: "Email", icon: Mail },
    { key: "send_file", label: "Send file", icon: Paperclip },
    { key: "meeting", label: "Meeting", icon: CalendarClock },
    { key: "other", label: "Other", icon: CircleDot },
  ];

export function kindOf(kind: TaskKind) {
  return TASK_KINDS.find((item) => item.key === kind) ?? TASK_KINDS[5];
}

export const BUCKETS: { key: TaskBucket; label: string }[] = [
  { key: "overdue", label: "Overdue" },
  { key: "today", label: "Today" },
  { key: "upcoming", label: "Upcoming" },
];

const clock = (at: Date) =>
  at.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

const date = (at: Date) =>
  at.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });

const dayStart = (at: Date) =>
  new Date(at.getFullYear(), at.getMonth(), at.getDate());

/** Whole days from `now`'s day to `at`'s day (0 today, 1 tomorrow, -1 yesterday). */
export function daysFrom(at: Date, now: Date): number {
  return Math.round(
    (dayStart(at).getTime() - dayStart(now).getTime()) / 86_400_000,
  );
}

/** When a task is due, the way the list says it: "5:30 PM", "Tomorrow, 10:00 AM". */
export function dueWords(
  task: Pick<TaskView, "starts_at">,
  now: Date = new Date(),
): string {
  const at = new Date(task.starts_at);
  const days = daysFrom(at, now);
  if (days === 0) return clock(at);
  if (days === 1) return `Tomorrow, ${clock(at)}`;
  if (days === -1) return `Yesterday, ${clock(at)}`;
  return `${date(at)}, ${clock(at)}`;
}

/** The list's heading counts: "Overdue 3". */
export function bucketLabel(
  bucket: { key: TaskBucket; label: string },
  counts: Partial<Record<TaskBucket, number>> | null,
): string {
  const count = counts?.[bucket.key] ?? 0;
  return count > 0 ? `${bucket.label} ${count}` : bucket.label;
}

export type QuickTime = { key: string; label: string; at: Date };

/** Remind's quick times: in an hour, this evening (before 5 PM), tomorrow morning. */
export function quickTimes(now: Date = new Date()): QuickTime[] {
  const hour = new Date(now.getTime() + 60 * 60_000);
  hour.setSeconds(0, 0);
  hour.setMinutes(Math.ceil(hour.getMinutes() / 5) * 5);
  const evening = dayStart(now);
  evening.setHours(18);
  const tomorrow = dayStart(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(10);
  return [
    { key: "hour", label: "In 1 hour", at: hour },
    ...(now.getHours() < 17
      ? [{ key: "evening", label: "This evening", at: evening }]
      : []),
    { key: "tomorrow", label: "Tomorrow 10 AM", at: tomorrow },
  ];
}

/** A Date as a datetime-local input's value, in the phone's own time. */
export function localInput(at: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(
    at.getHours(),
  )}:${pad(at.getMinutes())}`;
}

export const SNOOZES: {
  key: "15m" | "1h" | "evening" | "tomorrow";
  label: string;
}[] = [
  { key: "15m", label: "15 minutes" },
  { key: "1h", label: "1 hour" },
  { key: "evening", label: "This evening" },
  { key: "tomorrow", label: "Tomorrow" },
];
