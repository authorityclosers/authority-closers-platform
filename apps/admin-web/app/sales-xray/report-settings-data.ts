/**
 * Report settings versions (owner order, 19 Oct 2026): normalizer for
 * GET /v1/admin/conversation/report-settings and helpers for the editor.
 * Version 1 is today's Report, Prospect and Coaching, frozen; every change is
 * a new version and every choice a new history row.
 */
import { read } from "../lib/read";

export type Parameter = {
  key: string;
  surface: string;
  label: string;
  help: string;
  kind: "choice" | "toggle" | "number" | "pointers";
  choices: { value: string; label: string }[];
  minimum: number | null;
  maximum: number | null;
  applies: string;
  inApp: boolean;
  tunable: boolean;
  signals: string[];
};

export type Change = { key: string; from: unknown; to: unknown };

export type Version = {
  number: number;
  label: string;
  note: string | null;
  industryCode: string | null;
  baseNumber: number | null;
  origin: string;
  createdAt: string;
  settings: Record<string, unknown>;
  changes: Change[];
  organisations: number;
};

export type OrganisationRow = {
  tenantId: string;
  name: string;
  industryCode: string | null;
  versionNumber: number;
  source: string;
  ownVersionNumber: number | null;
};

export type HistoryRow = {
  id: string;
  kind: string;
  scope: string;
  tenantId: string | null;
  organisation: string | null;
  industryCode: string | null;
  versionNumber: number | null;
  previousVersionNumber: number | null;
  reason: string | null;
  createdAt: string;
};

export type ReportSettingsOverview = {
  parameters: Parameter[];
  versions: Version[];
  generalVersionNumber: number | null;
  industries: { industryCode: string; versionNumber: number }[];
  organisations: OrganisationRow[];
  history: HistoryRow[];
};

const n = read.number;
const on = read.optionalNumber;
const s = read.string;
const os = read.optionalString;

export function normalizeReportSettings(raw: unknown): ReportSettingsOverview {
  const body = read.object(raw);
  return {
    parameters: read.array(body.parameters).map((item) => {
      const row = read.object(item);
      const kind = s(row.kind);
      return {
        key: s(row.key),
        surface: s(row.surface),
        label: s(row.label, s(row.key)),
        help: s(row.help),
        kind: (["choice", "toggle", "number", "pointers"].includes(kind)
          ? kind
          : "toggle") as Parameter["kind"],
        choices: read.array(row.choices).map((choice) => {
          const value = read.object(choice);
          return {
            value: s(value.value),
            label: s(value.label, s(value.value)),
          };
        }),
        minimum: on(row.minimum),
        maximum: on(row.maximum),
        applies: s(row.applies, "display"),
        inApp: read.boolean(row.in_app),
        tunable: read.boolean(row.tunable),
        signals: read.strings(row.signals),
      };
    }),
    versions: read.array(body.versions).map((item) => {
      const row = read.object(item);
      return {
        number: n(row.number, 1),
        label: s(row.label, `Version ${n(row.number, 1)}`),
        note: os(row.note),
        industryCode: os(row.industry_code),
        baseNumber: on(row.base_number),
        origin: s(row.origin, "admin"),
        createdAt: s(row.created_at),
        settings: read.object(row.settings),
        changes: read.array(row.changes).map((value) => {
          const change = read.object(value);
          return { key: s(change.key), from: change.from, to: change.to };
        }),
        organisations: n(row.organisations),
      };
    }),
    generalVersionNumber: on(body.general_version_number),
    industries: read.array(body.industries).map((item) => {
      const row = read.object(item);
      return {
        industryCode: s(row.industry_code),
        versionNumber: n(row.version_number, 1),
      };
    }),
    organisations: read.array(body.organisations).map((item) => {
      const row = read.object(item);
      return {
        tenantId: s(row.tenant_id),
        name: s(row.name, "Unnamed"),
        industryCode: os(row.industry_code),
        versionNumber: n(row.version_number, 1),
        source: s(row.source, "built_in"),
        ownVersionNumber: on(row.own_version_number),
      };
    }),
    history: read.array(body.history).map((item) => {
      const row = read.object(item);
      return {
        id: s(row.id),
        kind: s(row.kind),
        scope: s(row.scope),
        tenantId: os(row.tenant_id),
        organisation: os(row.organisation),
        industryCode: os(row.industry_code),
        versionNumber: on(row.version_number),
        previousVersionNumber: on(row.previous_version_number),
        reason: os(row.reason),
        createdAt: s(row.created_at),
      };
    }),
  };
}

/** A dotted key's value in a nested settings object ("report.parts.outcome"). */
export function valueAt(
  settings: Record<string, unknown>,
  key: string,
): unknown {
  let current: unknown = settings;
  for (const part of key.split(".")) {
    if (typeof current !== "object" || current === null) return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

/** A copy of the settings with one dotted key changed; the input is untouched. */
export function withValue(
  settings: Record<string, unknown>,
  key: string,
  value: unknown,
): Record<string, unknown> {
  const [head, ...rest] = key.split(".");
  if (!head) return settings;
  if (!rest.length) return { ...settings, [head]: value };
  const child = read.object(settings[head]);
  return { ...settings, [head]: withValue(child, rest.join("."), value) };
}

export const SOURCE_LABEL: Record<string, string> = {
  organisation: "chosen for it",
  industry: "its industry's default",
  general: "the general default",
  built_in: "built in",
};

export const SURFACE_LABEL: Record<string, string> = {
  report: "Report",
  prospect: "Prospect",
  coaching: "Coaching",
};

/** A change in words: "Report style: Guided → Compact". */
export function describeChange(
  change: Change,
  parameters: Parameter[],
): string {
  const parameter = parameters.find((item) => item.key === change.key);
  const label = parameter
    ? `${SURFACE_LABEL[parameter.surface] ?? parameter.surface} · ${parameter.label}`
    : change.key;
  const word = (value: unknown) => {
    if (typeof value === "boolean") return value ? "on" : "off";
    if (Array.isArray(value)) return `${value.length} shown`;
    const choice = parameter?.choices.find((item) => item.value === value);
    return choice ? choice.label : String(value);
  };
  return `${label}: ${word(change.from)} → ${word(change.to)}`;
}

/** One history row in words. */
export function describeEvent(row: HistoryRow): string {
  if (row.kind === "version_created")
    return `Version ${row.versionNumber ?? "?"} created from version ${row.previousVersionNumber ?? 1}`;
  const target =
    row.scope === "organisation"
      ? (row.organisation ?? "An organisation")
      : row.scope === "industry"
        ? `Industry ${row.industryCode ?? "?"}`
        : "Everyone (general default)";
  const to =
    row.versionNumber === null
      ? "back to its default"
      : `version ${row.versionNumber}`;
  const from =
    row.previousVersionNumber === null
      ? "its default"
      : `version ${row.previousVersionNumber}`;
  return `${target}: ${from} → ${to}`;
}
