/**
 * The stage editor's rules (stages-views-sources.md §3, owner + Dipak, 30 Oct 2026),
 * apart from the screen so they are tested on their own. Every stage keeps one of
 * eight meanings, mapped onto the desk's kinds and milestones, so the numbers never
 * depend on a stage's name.
 */

import {
  newId,
  type Draft,
  type Kind,
  type StageView,
  type TemplatePreview,
} from "../../leads/journey/journey-client";

export type Meaning =
  | "untouched"
  | "not_reached"
  | "in_talks"
  | "interested"
  | "meeting"
  | "won"
  | "lost"
  | "junk";

export const MEANINGS: {
  key: Meaning;
  label: string;
  kind: Kind;
  milestone: string;
}[] = [
  { key: "untouched", label: "Untouched", kind: "new", milestone: "lead" },
  {
    key: "not_reached",
    label: "Not reached",
    kind: "not_connected",
    milestone: "unreachable",
  },
  {
    key: "in_talks",
    label: "In talks",
    kind: "follow_up",
    milestone: "contacted",
  },
  {
    key: "interested",
    label: "Interested",
    kind: "interested",
    milestone: "qualified",
  },
  {
    key: "meeting",
    label: "Meeting",
    kind: "interested",
    milestone: "appointment_booked",
  },
  { key: "won", label: "Won", kind: "won", milestone: "won" },
  { key: "lost", label: "Lost", kind: "lost", milestone: "lost" },
  { key: "junk", label: "Junk", kind: "junk", milestone: "disqualified" },
];

const MEETINGS = new Set(["appointment_booked", "appointment_done"]);
const CLOSED = new Set<Kind | undefined>(["won", "lost", "junk"]);
export const MAX_STAGES = 16;

export const live = (list: Draft[]) => list.filter((stage) => !stage.archived);

export function meaningOf(stage: { kind?: Kind; milestone?: string }): Meaning {
  switch (stage.kind) {
    case "new":
      return "untouched";
    case "not_connected":
      return "not_reached";
    case "interested":
      return MEETINGS.has(stage.milestone ?? "") ? "meeting" : "interested";
    case "won":
    case "lost":
    case "junk":
      return stage.kind;
    default:
      return "in_talks";
  }
}

export const meaningLabel = (meaning: Meaning) =>
  MEANINGS.find((item) => item.key === meaning)!.label;

/** Why this stage can't take that meaning, in one line, or null. */
export function meaningBlock(
  list: Draft[],
  stage: Draft,
  to: Meaning,
): string | null {
  if (meaningOf(stage) === to) return null;
  if (stage.kind === "new") return "The first stage is always untouched leads.";
  if (stage.kind === "not_connected")
    return "Every list keeps one Not reached.";
  const target = MEANINGS.find((item) => item.key === to)!;
  if (target.kind === "new" || target.kind === "not_connected")
    return "There is one of these already.";
  if (stage.leads > 0 && target.kind !== stage.kind)
    return "It has leads, so only Interested and Meeting swap.";
  if (
    target.kind === "junk" &&
    live(list).some((item) => item.kind === "junk" && item.id !== stage.id)
  )
    return "There is a Junk stage already.";
  return null;
}

export function withMeaning(stage: Draft, to: Meaning): Draft {
  if (meaningOf(stage) === to) return stage;
  const target = MEANINGS.find((item) => item.key === to)!;
  return { ...stage, kind: target.kind, milestone: target.milestone };
}

/** Ready stages "+ Add stage" offers first (§3), with the meaning each takes. */
export const READY: { label: string; milestone: string }[] = [
  { label: "Demo booked", milestone: "appointment_booked" },
  { label: "Site visit", milestone: "appointment_booked" },
  { label: "Payment pending", milestone: "negotiation" },
  { label: "Documents", milestone: "application" },
];

const same = (a: string, b: string) =>
  a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();

/** The ready stages this list doesn't have yet. */
export const readyLeft = (list: Draft[]) =>
  READY.filter(
    (item) => !live(list).some((stage) => same(stage.label, item.label)),
  );

/** Puts the stages live in this order, the archived ones after them. */
function arrange(list: Draft[], order: Draft[]): Draft[] {
  return [...order, ...list.filter((stage) => stage.archived)];
}

/** Where a new open stage goes: before Won, Lost and Junk. */
function openEnd(order: Draft[]): number {
  const at = order.findIndex((stage) => CLOSED.has(stage.kind));
  return at < 0 ? order.length : at;
}

/**
 * Adds a stage before the closed ones. A removed stage of the same name comes back
 * instead, with its key and its history.
 */
export function addStage(
  list: Draft[],
  stage: { label: string; kind: Kind; milestone: string },
  at?: number,
): Draft[] {
  const order = live(list);
  const back = list.find(
    (item) =>
      item.archived &&
      item.kind === stage.kind &&
      same(item.label, stage.label),
  );
  const added: Draft = back
    ? { ...back, archived: false, milestone: stage.milestone }
    : {
        id: newId(),
        label: stage.label.trim(),
        kind: stage.kind,
        milestone: stage.milestone,
        archived: false,
        leads: 0,
        visible: true,
        color: null,
        coldLabel: null,
      };
  const place = at ?? openEnd(order);
  return arrange(
    list.filter((item) => item.id !== added.id),
    [...order.slice(0, place), added, ...order.slice(place)],
  );
}

/** Moves a live stage to a new place; the New stage stays first. */
export function moveTo(list: Draft[], id: string, to: number): Draft[] {
  const order = live(list);
  const from = order.findIndex((stage) => stage.id === id);
  const place = Math.max(1, Math.min(to, order.length - 1));
  if (from < 1 || place === from) return list;
  const [stage] = order.splice(from, 1);
  order.splice(place, 0, stage);
  return arrange(list, order);
}

/** Why this stage can't be removed, in one line, or null. */
export function removeBlock(list: Draft[], stage: Draft): string | null {
  if (stage.kind === "new") return "The first stage stays. Rename it instead.";
  if (stage.kind === "not_connected")
    return "Every list keeps one Not reached.";
  if (
    (stage.kind === "won" || stage.kind === "lost") &&
    live(list).filter((item) => item.kind === stage.kind).length === 1
  )
    return stage.kind === "won"
      ? "Keep at least one Won stage."
      : "Keep at least one Lost stage.";
  return null;
}

/**
 * Where a removed stage's leads may go, as the server allows (journey place_choices):
 * an open stage's to another open stage, never back to New; Won and Lost to their own
 * kind; Junk to Lost when no Junk is left.
 */
export function destinations(list: Draft[], stage: Draft): Draft[] {
  const others = live(list).filter((item) => item.id !== stage.id);
  if (stage.kind === "junk")
    return others.filter((item) => item.kind === "lost");
  if (CLOSED.has(stage.kind))
    return others.filter((item) => item.kind === stage.kind);
  return others.filter((item) => !CLOSED.has(item.kind) && item.kind !== "new");
}

export const removed = (list: Draft[], id: string): Draft[] =>
  list.map((stage) => (stage.id === id ? { ...stage, archived: true } : stage));

/** The two meeting stages of §2, each one switch. */
export const MEETING_STAGES = [
  {
    key: "meeting_scheduled",
    label: "Meeting Scheduled",
    milestone: "appointment_booked",
  },
  { key: "meeting_done", label: "Meeting Done", milestone: "appointment_done" },
] as const;
export type MeetingStage = (typeof MEETING_STAGES)[number];

/** The live stage a meeting switch stands for: by its key, else its name, else the
 *  first stage that means it ("Meeting/Demo completed" is Meeting Done). */
export function meetingStage(
  list: Draft[],
  which: MeetingStage,
): Draft | undefined {
  const order = live(list);
  return (
    order.find((stage) => stage.key === which.key) ??
    order.find((stage) => same(stage.label, which.label)) ??
    order.find(
      (stage) =>
        stage.kind === "interested" && stage.milestone === which.milestone,
    )
  );
}

/** Turns a meeting stage on: back from history when it was there, before Meeting
 *  Done when that one is on, else before the closed stages. */
export function meetingOn(list: Draft[], which: MeetingStage): Draft[] {
  if (meetingStage(list, which)) return list;
  const back = list.find((stage) => stage.archived && stage.key === which.key);
  const order = live(list);
  const done =
    which.key === "meeting_scheduled"
      ? meetingStage(list, MEETING_STAGES[1])
      : undefined;
  const at = done
    ? order.findIndex((stage) => stage.id === done.id)
    : openEnd(order);
  if (back) {
    const revived = { ...back, archived: false };
    return arrange(
      list.filter((stage) => stage.id !== back.id),
      [...order.slice(0, at), revived, ...order.slice(at)],
    );
  }
  return addStage(
    list,
    { label: which.label, kind: "interested", milestone: which.milestone },
    at,
  );
}

/**
 * "Use recommended": where each of today's stages' leads go, by meaning. A stage
 * goes to the recommended stage with its own milestone, else with its meaning, else
 * where the server would put it; never into the first stage unless it was new.
 */
export function recommendedMap(
  before: StageView[],
  preview: TemplatePreview,
): Record<string, string> {
  const map: Record<string, string> = {};
  for (const landing of preview.landings) {
    if (!landing.leads) continue;
    const from = before.find((stage) => stage.key === landing.fromKey);
    const choices = preview.stages.filter(
      (stage) =>
        landing.choices.includes(stage.key) &&
        (stage.kind !== "new" || from?.kind === "new"),
    );
    const picked =
      choices.find((stage) => stage.milestone === from?.milestone) ??
      choices.find((stage) => from && meaningOf(stage) === meaningOf(from)) ??
      choices.find((stage) => stage.key === landing.toKey) ??
      choices[0];
    if (picked) map[landing.fromKey] = picked.key;
  }
  return map;
}
