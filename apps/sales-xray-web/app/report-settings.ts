/**
 * Report settings for this workspace (owner order, 19 Oct 2026): Admin keeps
 * numbered versions of how Report, Prospect and Coaching present a call and
 * chooses one per organisation, industry or everyone. Version 1 is today's
 * report; an older server, a guest or any read failure gets version 1, so
 * nothing disappears because of a settings problem.
 */
import { useEffect, useState } from "react";

import { acquisition } from "./acquisition-client";

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

let cached: Promise<AppReportSettings> | null = null;

/** One read per page load; any failure means version 1. */
export function loadReportSettings(): Promise<AppReportSettings> {
  cached ??= acquisition("/report-settings")
    .then(parseReportSettings)
    .catch(() => VERSION_1);
  return cached;
}

/** The workspace's settings; version 1 until (or unless) the read answers. */
export function useReportSettings(enabled: boolean): AppReportSettings {
  const [settings, setSettings] = useState<AppReportSettings>(VERSION_1);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void loadReportSettings().then((value) => {
      if (live) setSettings(value);
    });
    return () => {
      live = false;
    };
  }, [enabled]);
  return settings;
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
