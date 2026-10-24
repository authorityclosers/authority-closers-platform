"use client";

/**
 * The lead's path and history filters (Lead OS; spec section 5): every stage it
 * has been in, oldest first, with how long it stayed ("New 2 h → Not Connected
 * 1 d → Interested now"), and chips that narrow the history to stage moves,
 * calls, chats, meetings or notes. The history itself stays one line of time.
 */

import type { LeadEvent } from "../leads-client";
import styles from "./pipeline.module.css";

export type TimelineFilter =
  | "all"
  | "stages"
  | "calls"
  | "chats"
  | "meetings"
  | "notes";

export const FILTERS: { key: TimelineFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "stages", label: "Stages" },
  { key: "calls", label: "Calls" },
  { key: "chats", label: "Chats" },
  { key: "meetings", label: "Meetings" },
  { key: "notes", label: "Notes" },
];

/** Whether an event moved the lead (a stage move, or a call that moved it). */
export function isMove(event: LeadEvent): boolean {
  if (event.kind === "stage") return true;
  return event.kind === "result" && Boolean(event.action);
}

/** Whether a history line belongs under a filter chip. */
export function shows(
  filter: TimelineFilter,
  event: LeadEvent | "chat",
): boolean {
  if (filter === "all") return true;
  if (event === "chat") return filter === "chats";
  switch (filter) {
    case "stages":
      return (
        isMove(event) || event.kind === "captured" || event.kind === "repeat"
      );
    case "calls":
      return event.kind === "call" || event.kind === "result";
    case "chats":
      return event.kind === "message";
    case "meetings":
      return event.kind === "meeting";
    case "notes":
      return event.kind === "note";
    default:
      return true;
  }
}

function span(from: number, to: number): string {
  const minutes = Math.max(0, Math.round((to - from) / 60_000));
  if (minutes < 60) return `${Math.max(1, minutes)} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.round(hours / 24);
  return `${days} d`;
}

export type PathStep = {
  label: string;
  at: string;
  age: string | null;
  now: boolean;
};

/**
 * The stages the lead has been in, oldest first, from its history (newest
 * first, as the lead's detail sends it) and its current stage's name.
 */
export function stagePath(
  events: LeadEvent[],
  currentLabel: string,
  now: Date = new Date(),
): PathStep[] {
  const oldest = [...events].reverse();
  const moves = oldest.filter((event) => isMove(event) && event.stage_label);
  const captured = oldest.find((event) => event.kind === "captured");
  const steps: { label: string; at: string }[] = [];
  if (moves.length)
    steps.push({
      label: moves[0].from_label ?? "New",
      at: captured?.at ?? moves[0].at,
    });
  for (const move of moves) {
    const label = move.stage_label as string;
    if (steps[steps.length - 1]?.label !== label)
      steps.push({ label, at: move.at });
  }
  if (!steps.length)
    steps.push({ label: currentLabel, at: captured?.at ?? now.toISOString() });
  else if (steps[steps.length - 1].label !== currentLabel)
    steps.push({ label: currentLabel, at: steps[steps.length - 1].at });
  return steps.map((step, index) => {
    const last = index === steps.length - 1;
    const end = last ? now.getTime() : Date.parse(steps[index + 1].at);
    return {
      label: step.label,
      at: step.at,
      age: span(Date.parse(step.at), end),
      now: last,
    };
  });
}

export function StagePath({
  events,
  currentLabel,
}: {
  events: LeadEvent[];
  currentLabel: string;
}) {
  const steps = stagePath(events, currentLabel);
  if (steps.length < 2) return null;
  // The last few stages fit a phone; the whole path is in the history below.
  const shown = steps.slice(-5);
  return (
    <ol className={styles.path} aria-label="Stages so far">
      {shown.map((step, index) => (
        <li
          key={`${step.label}-${step.at}-${index}`}
          data-now={step.now ? "" : undefined}
        >
          <span>{step.label}</span>
          <span className={styles.pathAge}>
            {step.now ? `now · ${step.age}` : step.age}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function TimelineFilters({
  value,
  onChange,
}: {
  value: TimelineFilter;
  onChange: (next: TimelineFilter) => void;
}) {
  return (
    <div
      className={styles.filters}
      role="group"
      aria-label="Show in the history"
    >
      {FILTERS.map((item) => (
        <button
          key={item.key}
          type="button"
          className={styles.chip}
          aria-pressed={value === item.key}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

const SOURCE_WORDS: Record<string, string> = {
  ai_suggestion: "Suggested",
  rule: "Rule",
  import: "Import",
  merge: "Merged",
  capture: "Came again",
};

/** A small badge for how a move was made, when not by hand. */
export function sourceBadge(event: LeadEvent): string | null {
  return event.move_source ? (SOURCE_WORDS[event.move_source] ?? null) : null;
}
