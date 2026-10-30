/**
 * How a stage looks wherever it is shown: the stage editor, its phone preview and the
 * seller's Leads tabs (owner + Dipak, 30 Oct 2026). Its colour dot as a palette token,
 * and its name on the Inbound Leads or Cold Leads side.
 */

import type { Kind, StageColor } from "./journey-client";

export type Side = "inbound" | "cold";

const TOKENS: Record<StageColor, string> = {
  teal: "var(--lx-teal)",
  blue: "var(--lx-closing)",
  violet: "var(--lx-missed)",
  amber: "var(--lx-warning)",
  green: "var(--lx-success)",
  red: "var(--lx-danger)",
  slate: "var(--lx-info)",
  pink: "var(--lx-objection)",
};

export const COLOR_WORDS: Record<StageColor, string> = {
  teal: "Teal",
  blue: "Blue",
  violet: "Violet",
  amber: "Amber",
  green: "Green",
  red: "Red",
  slate: "Grey",
  pink: "Pink",
};

// A stage with no dot of its own takes its meaning's colour.
const BY_KIND: Record<Kind, StageColor> = {
  new: "blue",
  not_connected: "slate",
  follow_up: "teal",
  interested: "amber",
  won: "green",
  lost: "red",
  junk: "slate",
};
const MEETINGS = new Set(["appointment_booked", "appointment_done"]);

type Looks = {
  kind?: Kind;
  milestone?: string;
  color?: StageColor | null;
};

/** The stage's colour: its own dot, else its meaning's. */
export function stageColor(stage: Looks): StageColor {
  if (stage.color) return stage.color;
  if (stage.kind === "interested" && MEETINGS.has(stage.milestone ?? ""))
    return "violet";
  return BY_KIND[stage.kind ?? "follow_up"];
}

/** The stage's colour as CSS (a palette token, for a `--stage` custom property). */
export const stageTone = (stage: Looks) => TOKENS[stageColor(stage)];

export const colorTone = (color: StageColor) => TOKENS[color];

/** A stage's name on one side: the New stage may have its own Cold Leads name. */
export function stageName(
  stage: { kind?: Kind; label: string; coldLabel?: string | null },
  side: Side,
): string {
  return side === "cold" && stage.kind === "new" && stage.coldLabel
    ? stage.coldLabel
    : stage.label;
}
