/**
 * Admin → Settings: every setting Admin controls in one list, with its value
 * now, its last change and where to change it. Each area comes from the read
 * its own page already uses, read leniently, so one unavailable area never
 * hides the others. The same list becomes the registry behind the Admin API
 * and CLI (Phase 6). Pure.
 */
import { read } from "../lib/read";
import type { CallDataSettings } from "../sales-xray/call-data-model";
import type { ReportSettingsOverview } from "../sales-xray/report-settings-data";

/** id: the registry setting this row shows (GET /v1/admin/settings), changed in place. */
export type SettingRow = {
  label: string;
  value: string;
  note?: string;
  id?: string;
};

export type SettingsArea = {
  key: string;
  title: string;
  what: string;
  href: string;
  revision: string | null;
  changedAt: string | null;
  rows: SettingRow[];
  /** Why this area could not be read; its rows are then empty. */
  unavailable: string | null;
};

type Read<T> = { ok: true; data: T } | { ok: false; error: string };

const yesNo = (value: unknown, yes: string, no: string) =>
  value === true ? yes : value === false ? no : "—";

const rupeesFromPaise = (paise: unknown) =>
  typeof paise === "number"
    ? new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 0,
      }).format(paise / 100)
    : "—";

const rupees = (value: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(value);

function words(value: string) {
  const spaced = value.replaceAll(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const LANGUAGE: Record<string, string> = {
  en: "English",
  "hi-Deva+en": "Hindi and English",
  "mr-Deva+en": "Marathi and English",
};

function area(
  base: Omit<SettingsArea, "rows" | "unavailable" | "revision" | "changedAt">,
  result: Read<unknown>,
  build: (data: never) => Pick<SettingsArea, "rows" | "revision" | "changedAt">,
): SettingsArea {
  if (!result.ok)
    return {
      ...base,
      rows: [],
      revision: null,
      changedAt: null,
      unavailable: result.error,
    };
  return { ...base, ...build(result.data as never), unavailable: null };
}

export function providerArea(result: Read<unknown>): SettingsArea {
  return area(
    {
      key: "providers",
      title: "AI providers and models",
      what: "Which provider and model runs each step, and whether paid AI may run",
      href: "/sales-xray/providers",
    },
    result,
    (raw: unknown) => {
      const body = read.object(raw);
      const current = read.object(body.current);
      const configuration = read.object(current.configuration);
      const policy = read.object(configuration.policy);
      const routes = read.array(configuration.routes).map((item) => {
        const route = read.object(item);
        return {
          label: words(read.string(route.task, "Step")),
          value: `${read.string(route.provider_id, "—")} · ${read.string(route.model_id, "—")}`,
          note: read.optionalString(route.prompt_revision) ?? undefined,
        };
      });
      return {
        revision:
          read.optionalNumber(current.revision) !== null
            ? String(read.number(current.revision))
            : null,
        changedAt: read.optionalString(current.created_at),
        rows: [
          {
            label: "Hosted AI",
            value: yesNo(
              body.execution_activated ?? current.execution_activated,
              "Switched on",
              "Switched off",
            ),
          },
          {
            id: "providers.paid_allowed",
            label: "Paid providers",
            value: yesNo(policy.allow_paid, "Allowed", "Not allowed"),
          },
          ...(routes.length
            ? routes
            : [{ label: "Steps", value: "No saved routes yet" }]),
        ],
      };
    },
  );
}

export function analysisArea(result: Read<unknown>): SettingsArea {
  return area(
    {
      key: "analysis",
      title: "Analysis engine",
      what: "How long each AI step may answer, the coaching prompt and the report language",
      href: "/sales-xray/analysis",
    },
    result,
    (raw: unknown) => {
      const body = read.object(raw);
      const settings = read.object(body.settings);
      const number = (key: string) =>
        read.optionalNumber(settings[key]) === null
          ? "—"
          : read.number(settings[key]).toLocaleString("en-IN");
      return {
        revision:
          read.optionalNumber(body.revision) !== null
            ? String(read.number(body.revision))
            : null,
        changedAt: read.optionalString(body.created_at),
        rows: [
          {
            id: "analysis.facts_max_requests",
            label: "Facts: most AI requests per call",
            value: number("c4_max_requests"),
          },
          {
            id: "analysis.facts_max_tokens",
            label: "Facts: longest answer",
            value: `${number("c4_max_completion_tokens")} tokens`,
          },
          {
            id: "analysis.report_max_tokens",
            label: "Report: longest answer",
            value: `${number("c5_max_completion_tokens")} tokens`,
          },
          {
            id: "analysis.report_detail",
            label: "Report detail",
            value: words(read.string(settings.c5_output_profile, "—")),
          },
          {
            id: "analysis.coaching_prompt",
            label: "Coaching prompt",
            value: read.string(settings.c5_coaching_prompt_revision, "—"),
          },
          {
            id: "analysis.report_language",
            label: "Report language",
            value:
              LANGUAGE[read.string(settings.report_language_default)] ??
              read.string(settings.report_language_default, "—"),
          },
        ],
      };
    },
  );
}

/** The budget's period in words: the cap and what is left count only this period. */
const PERIOD: Record<string, string> = {
  lifetime: "in total",
  monthly: "this month",
  daily: "today",
};

export function executionArea(
  result: Read<unknown>,
  /** GET /v1/admin/conversation/budget: the owner's ceiling and period, when readable. */
  budgetSettings: Read<unknown> | null = null,
): SettingsArea {
  return area(
    {
      key: "execution",
      title: "Running and AI budget",
      what: "Whether analyses run, the AI budget and what is left of it",
      href: "/sales-xray/execution",
    },
    result,
    (raw: unknown) => {
      const body = read.object(raw);
      const control = read.object(body.control);
      const budget = body.budget ? read.object(body.budget) : null;
      const waiting = read.optionalNumber(body.waiting_calls);
      const settings =
        budgetSettings?.ok && read.object(budgetSettings.data).settings
          ? read.object(read.object(budgetSettings.data).settings)
          : null;
      const period = settings ? read.string(settings.period) : "";
      const periodWords = PERIOD[period] ?? (period ? words(period) : null);
      return {
        revision:
          read.optionalNumber(control.revision) !== null
            ? String(read.number(control.revision))
            : null,
        changedAt: read.optionalString(control.changed_at),
        rows: [
          {
            id: "execution.paused",
            label: "Analyses",
            value: yesNo(control.paused, "Paused", "Running"),
          },
          ...(budget
            ? [
                {
                  id: "budget.cap_paise",
                  label: "AI budget",
                  value: rupeesFromPaise(budget.cap_paise),
                  note: periodWords ?? undefined,
                },
                ...(settings &&
                read.optionalNumber(settings.ceiling_paise) !== null
                  ? [
                      {
                        id: "budget.ceiling_paise",
                        label: "Ceiling",
                        value: rupeesFromPaise(settings.ceiling_paise),
                        note: "the most the budget can be raised to",
                      },
                    ]
                  : []),
                {
                  label: "Left",
                  value: rupeesFromPaise(budget.available_paise),
                  note: words(read.string(budget.warning, "")) || undefined,
                },
              ]
            : [{ label: "AI budget", value: "Not set" }]),
          ...(waiting !== null
            ? [
                {
                  label: "Calls waiting for budget",
                  value: waiting.toLocaleString("en-IN"),
                },
              ]
            : []),
        ],
      };
    },
  );
}

export function callDataArea(result: Read<CallDataSettings>): SettingsArea {
  return area(
    {
      key: "call-data",
      title: "Call data engine",
      what: "The fast and deep reads of every call: switch, model and daily cap",
      href: "/sales-xray/call-data",
    },
    result,
    (data: CallDataSettings) => {
      const pipeline = (key: "fast" | "deep", label: string): SettingRow[] => {
        const config = data.config[key];
        const id = `call_data.${key}`;
        return [
          {
            id: `${id}.enabled`,
            label,
            value: config.enabled ? "On" : "Off",
            note: `${rupees(data.spentToday[key])} spent today${
              data.status[key].atCap ? " · cap reached" : ""
            }${data.status[key].waiting ? ` · ${data.status[key].waiting} waiting` : ""}`,
          },
          {
            id: `${id}.model`,
            label: `${label}: model`,
            value: config.model || "—",
          },
          {
            id: `${id}.daily_cap_inr`,
            label: `${label}: daily cap`,
            value: `₹${config.dailyCapInr.toLocaleString("en-IN")} a day`,
          },
          {
            id: `${id}.max_call_minutes`,
            label: `${label}: longest call`,
            value: `${config.maxCallMinutes} min`,
          },
        ];
      };
      return {
        revision: data.revision !== null ? String(data.revision) : null,
        changedAt: data.history[0]?.at ?? null,
        rows: [
          ...pipeline("fast", "Fast pipeline"),
          ...pipeline("deep", "Deep pipeline"),
          {
            label: "Live transcription",
            value: data.config.streaming.provider
              ? `${data.config.streaming.provider} · ${data.config.streaming.model || "—"}`
              : "Not set",
            note: data.config.streaming.provider
              ? data.config.streaming.language || undefined
              : undefined,
          },
        ],
      };
    },
  );
}

export function reportArea(result: Read<ReportSettingsOverview>): SettingsArea {
  return area(
    {
      key: "report",
      title: "Report versions",
      what: "Which version of Report, Prospect and Coaching each organisation sees",
      href: "/sales-xray/report-settings",
    },
    result,
    (data: ReportSettingsOverview) => {
      const own = data.organisations.filter(
        (row) => row.ownVersionNumber !== null,
      ).length;
      return {
        revision: null,
        changedAt: data.history[0]?.createdAt ?? null,
        rows: [
          {
            label: "Everyone uses",
            value: `Version ${data.generalVersionNumber ?? 1}`,
            note: data.generalVersionNumber === null ? "built in" : undefined,
          },
          {
            label: "Saved versions",
            value: data.versions.length.toLocaleString("en-IN"),
          },
          {
            label: "Industry defaults",
            value: data.industries.length
              ? data.industries
                  .map(
                    (item) =>
                      `${item.industryCode} → Version ${item.versionNumber}`,
                  )
                  .join(", ")
              : "None",
          },
          {
            label: "Organisations with their own version",
            value: `${own} of ${data.organisations.length}`,
          },
        ],
      };
    },
  );
}
