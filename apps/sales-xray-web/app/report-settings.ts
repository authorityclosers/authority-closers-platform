/**
 * Report settings for this workspace (owner order, 19 Oct 2026): Admin keeps
 * numbered versions of how Report, Prospect and Coaching present a call and
 * chooses one per organisation, industry or everyone. Version 1 is today's
 * report; an older server, a guest or any read failure gets version 1, so
 * nothing disappears because of a settings problem.
 *
 * The version that applies is resolved on the server (the organisation's own
 * choice, its industry's default, the general default, version 1), so the
 * per-industry tailoring arrives here as just "the version". Nothing here
 * re-analyses a call or spends anything: a version only changes how a saved
 * call is shown.
 */
import { createContext, useContext, useEffect, useState } from "react";

import { acquisition } from "./acquisition-client";
import { identityOf } from "./calls-cache";
import { useWorkspaceAccess } from "./workspace-access";

export type AppReportSettings = {
  version: number;
  source: string;
  parts: { overview: boolean; analysis: boolean; outcome: boolean };
  prospect: boolean;
  coaching: boolean;
  /** The whole saved document, for tabs that adopt more of it. */
  settings: Record<string, unknown>;
};

export const VERSION_1: AppReportSettings = {
  version: 1,
  source: "built_in",
  parts: { overview: true, analysis: true, outcome: true },
  prospect: true,
  coaching: true,
  settings: {},
};

const object = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const on = (value: unknown) => value !== false;

export function parseReportSettings(raw: unknown): AppReportSettings {
  const body = object(raw);
  const settings = object(body.settings);
  const report = object(settings.report);
  const parts = object(report.parts);
  const version = object(body.version).number;
  const parsed = {
    version: typeof version === "number" && version >= 1 ? version : 1,
    source: typeof body.source === "string" ? body.source : "built_in",
    parts: {
      overview: on(parts.overview),
      analysis: on(parts.analysis),
      outcome: on(parts.outcome),
    },
    prospect: on(object(settings.prospect).enabled),
    coaching: on(object(settings.coaching).enabled),
    settings,
  };
  // The server never saves a Report with no part; never show an empty one either.
  if (!parsed.parts.overview && !parsed.parts.analysis && !parsed.parts.outcome)
    parsed.parts = { ...VERSION_1.parts };
  return parsed;
}

// One read per workspace for the tab's life: a page that opens another call
// asks nothing again, and another workspace gets its own version.
const reads = new Map<string, Promise<AppReportSettings>>();
// Answers already in, so a Report opened after them paints in its version
// at once instead of version 1 for a moment.
const answers = new Map<string, AppReportSettings>();

/** One read per identity (``null``: one per page load); any failure means version 1. */
export function loadReportSettings(
  identity: string | null = null,
): Promise<AppReportSettings> {
  const key = identity ?? "";
  let read = reads.get(key);
  if (!read) {
    if (reads.size >= 4) forgetReportSettings();
    read = acquisition("/report-settings")
      .then(parseReportSettings)
      .catch(() => VERSION_1)
      .then((settings) => {
        answers.set(key, settings);
        return settings;
      });
    reads.set(key, read);
  }
  return read;
}

/** Forget every read (tests, and signing out). */
export function forgetReportSettings() {
  reads.clear();
  answers.clear();
}

/** The workspace's settings; version 1 until (or unless) the read answers. */
export function useReportSettings(enabled: boolean): AppReportSettings {
  const access = useWorkspaceAccess();
  const identity = identityOf(access?.context ?? null);
  const [loaded, setLoaded] = useState<{
    identity: string | null;
    settings: AppReportSettings;
  } | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void loadReportSettings(identity).then((settings) => {
      if (live) setLoaded({ identity, settings });
    });
    return () => {
      live = false;
    };
  }, [enabled, identity]);
  if (!enabled) return VERSION_1;
  // A workspace switch never shows the last workspace's version meanwhile.
  if (loaded && loaded.identity === identity) return loaded.settings;
  return answers.get(identity ?? "") ?? VERSION_1;
}

/** The Report's parts and the Prospect and Coaching tabs this version shows. */
export function applyReportSettings<T extends { id: string }>(
  panels: { story: T[]; prospect: T[]; coaching: T[] },
  settings: AppReportSettings,
): { story: T[]; prospect: T[]; coaching: T[] } {
  const part = (id: string) =>
    id === "overview"
      ? settings.parts.overview
      : id === "analysis"
        ? settings.parts.analysis
        : id === "outcome"
          ? settings.parts.outcome
          : true;
  const story = panels.story.filter((panel) => part(panel.id));
  return {
    story: story.length ? story : panels.story,
    prospect: settings.prospect ? panels.prospect : [],
    coaching: settings.coaching ? panels.coaching : [],
  };
}

/* ---------- How a version presents a call (its "look") ---------- */

export type ReportStyle = "guided" | "compact" | "scorecard";
export type Detail = "simple" | "standard" | "expert";

export const PROSPECT_SECTIONS = [
  "quality",
  "chips",
  "facts",
  "problem",
  "wants",
  "blockers",
  "personal",
  "follow_up",
  "next_action",
  "buyer_info",
] as const;
export type ProspectSection = (typeof PROSPECT_SECTIONS)[number];

export type ReportLook = {
  version: number;
  /** Guided is today's Report; compact and scorecard read faster. */
  style: ReportStyle;
  detail: Detail;
  /** The pointers listed, in this order; null: all 27 in the Report's order. */
  pointers: readonly string[] | null;
  /** The most pointers listed before "Show all"; null: no limit. */
  maxPointers: number | null;
  scores: boolean;
  /** Classic: the 27 pointers. Brain 4.0 beta: also its 18 skills, when saved. */
  scoring: "classic" | "brain4_beta";
  /** Quotes and moments under a pointer (never at the simple detail). */
  evidence: boolean;
  /** How to improve and its training video (never at the simple detail). */
  tips: boolean;
  prospect: {
    detail: Detail;
    sections: Readonly<Record<ProspectSection, boolean>>;
    /** The AI's own reads (urgency, fit, the suggested next action). */
    inferred: boolean;
  };
  coaching: {
    detail: Detail;
    moments: boolean;
    /** The most moments; null: every moment, as today. */
    maxMoments: number | null;
    acrossCalls: boolean;
  };
};

const ALL_SECTIONS = Object.fromEntries(
  PROSPECT_SECTIONS.map((key) => [key, true]),
) as Record<ProspectSection, boolean>;

/** Version 1: today's Report, Prospect and Coaching, exactly. */
export const VERSION_1_LOOK: ReportLook = {
  version: 1,
  style: "guided",
  detail: "standard",
  pointers: null,
  maxPointers: null,
  scores: true,
  scoring: "classic",
  evidence: true,
  tips: true,
  prospect: { detail: "standard", sections: ALL_SECTIONS, inferred: true },
  coaching: {
    detail: "standard",
    moments: true,
    maxMoments: null,
    acrossCalls: true,
  },
};

const choice = <T extends string>(
  value: unknown,
  allowed: readonly T[],
  fallback: T,
): T =>
  typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
const DETAILS = ["simple", "standard", "expert"] as const;
const whole = (value: unknown, low: number, high: number) =>
  typeof value === "number" && Number.isInteger(value)
    ? Math.min(high, Math.max(low, value))
    : null;

/**
 * The look a published version asks for. Version 1 (and anything the app
 * can't read) is today's look, so nothing changes until a version is published
 * or chosen for this workspace.
 */
export function reportLook(settings: AppReportSettings): ReportLook {
  if (settings.version <= 1) return VERSION_1_LOOK;
  const report = object(settings.settings.report);
  const prospect = object(settings.settings.prospect);
  const coaching = object(settings.settings.coaching);
  const detail = choice(report.complexity, DETAILS, "standard");
  const ids = Array.isArray(report.pointers)
    ? report.pointers.filter((id): id is string => typeof id === "string")
    : null;
  const maxPointers = whole(report.max_pointers, 3, 27);
  const maxMoments = whole(coaching.max_moments, 1, 10);
  const sections = object(prospect.sections);
  return {
    version: settings.version,
    style: choice(report.style, ["guided", "compact", "scorecard"], "guided"),
    detail,
    pointers: ids && ids.length ? ids : null,
    maxPointers: maxPointers !== null && maxPointers < 27 ? maxPointers : null,
    scores: on(report.show_scores),
    scoring: choice(report.scoring, ["classic", "brain4_beta"], "classic"),
    evidence: on(report.show_evidence) && detail !== "simple",
    tips: on(report.show_how_to_improve) && detail !== "simple",
    prospect: {
      detail: choice(prospect.complexity, DETAILS, "standard"),
      sections: Object.fromEntries(
        PROSPECT_SECTIONS.map((key) => [key, on(sections[key])]),
      ) as Record<ProspectSection, boolean>,
      inferred: on(prospect.show_inferred),
    },
    coaching: {
      detail: choice(coaching.complexity, DETAILS, "standard"),
      moments: on(coaching.show_moments),
      maxMoments,
      acrossCalls: on(coaching.show_across_calls),
    },
  };
}

/** The look of the Report being shown; version 1 wherever none is given. */
export const ReportLookContext = createContext<ReportLook>(VERSION_1_LOOK);

export function useReportLook(): ReportLook {
  return useContext(ReportLookContext);
}

/** The pointers a look lists: its choice, in its order (all of them by default). */
export function lookPointers<T extends { id: string }>(
  pointers: readonly T[],
  look: Pick<ReportLook, "pointers">,
): T[] {
  if (!look.pointers) return [...pointers];
  const byId = new Map(pointers.map((pointer) => [pointer.id, pointer]));
  const chosen = look.pointers
    .map((id) => byId.get(id))
    .filter((pointer): pointer is T => pointer !== undefined);
  // A version naming no pointer this Report has keeps them all.
  return chosen.length ? chosen : [...pointers];
}
