/**
 * How a stage looks wherever it is shown: the stage editor, its phone preview and the
 * seller's Leads tabs (owner + Dipak, 30-31 Oct 2026). Its colour dot as a palette token,
 * and its name on the Inbound Leads or Cold Leads side.
 */

import type { Kind, StageColor } from "./journey-client";

export type Side = "inbound" | "cold";

// Ten dots, each its own hue (owner, 31 Oct 2026: "every swatch distinct"). Indigo, violet
// and grey are mixed from palette tokens, so light and dark follow the theme.
const TOKENS: Record<StageColor, string> = {
  blue: "var(--lx-closing)",
  teal: "var(--lx-teal)",
  green: "var(--xr-green-mark)",
  amber: "var(--lx-warning)",
  red: "var(--lx-danger)",
  pink: "var(--lx-objection)",
  violet: "color-mix(in oklab, var(--lx-missed) 55%, var(--lx-objection))",
  indigo: "var(--lx-missed)",
  slate: "var(--lx-info)",
  grey: "color-mix(in oklab, var(--lx-muted) 45%, var(--sx-surface))",
};

export const COLOR_WORDS: Record<StageColor, string> = {
  blue: "Blue",
  teal: "Teal",
  green: "Green",
  amber: "Amber",
  red: "Red",
  pink: "Pink",
  violet: "Violet",
  indigo: "Indigo",
  slate: "Slate",
  grey: "Grey",
};

// A stage with no dot of its own takes its meaning's colour: Dipak's nine are all
// different (New Lead blue, Open Leads teal, Not Connected slate, Interested amber,
// Meeting Scheduled violet, Meeting Done indigo, Won green, Closed / Lost red, Junk grey).
const BY_KIND: Record<Kind, StageColor> = {
  new: "blue",
  not_connected: "slate",
  follow_up: "teal",
  interested: "amber",
  won: "green",
  lost: "red",
  junk: "grey",
};

type Looks = {
  kind?: Kind;
  milestone?: string;
  color?: StageColor | null;
};

/** The stage's colour: its own dot, else its meaning's. */
export function stageColor(stage: Looks): StageColor {
  if (stage.color) return stage.color;
  if (stage.kind === "interested" && stage.milestone === "appointment_booked")
    return "violet";
  if (stage.kind === "interested" && stage.milestone === "appointment_done")
    return "indigo";
  return BY_KIND[stage.kind ?? "follow_up"];
}

/** The stage's colour as CSS (a palette token, for a `--stage` custom property). */
export const stageTone = (stage: Looks) => TOKENS[stageColor(stage)];

export const colorTone = (color: StageColor) => TOKENS[color];

/** The stock first-stage names: on Cold Leads they read Unworked. */
const STOCK_NEW = new Set(["new", "new lead", "new leads"]);

/** A stage's name on one side: the New stage may have its own Cold Leads name;
 *  a list that never named it says Unworked there, as Home does (phone
 *  personas ph1-48, 1 Nov 2026: the import said "New lead", Home "Unworked"). */
export function stageName(
  stage: { kind?: Kind; label: string; coldLabel?: string | null },
  side: Side,
): string {
  if (side !== "cold" || stage.kind !== "new") return stage.label;
  if (stage.coldLabel) return stage.coldLabel;
  return STOCK_NEW.has(stage.label.trim().toLowerCase())
    ? "Unworked"
    : stage.label;
}
