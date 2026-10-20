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
  /** AI replies to leads at their cap or waiting: "Raise and resume". */
  raise?: {
    revision: number | null;
    to: number;
    atCap: boolean;
    waiting: number;
  };
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

// How the cap is counted: its name, the cap's words, and this period's spend.
const AI_PERIOD: Record<string, [string, string, string]> = {
  daily: ["Each day", "a day", "today"],
  monthly: ["Each month", "a month", "this month"],
  lifetime: ["In total", "in total", "in total"],
};

/**
 * AI replies to leads (the Lead Desk's GET /v1/admin/lead-desk-ai, 20 Oct):
 * the switch, model, cap and how it is counted, each changed in place, with
 * this period's spend and "Raise and resume" when it waits for budget.
 */
export function leadDeskAiArea(result: Read<unknown>): SettingsArea {
  const base = {
    key: "lead-desk-ai",
    title: "AI replies to leads",
    what: "Drafts and automatic replies to lead messages: switch, model and cap",
    href: "",
  };
  return area(base, result, (raw: unknown) => {
    const data = read.object(raw);
    const config = read.object(data.config);
    const status = read.object(data.status);
    const models = Array.isArray(data.models) ? data.models : [];
    const history = Array.isArray(data.history) ? data.history : [];
    const period = typeof config.period === "string" ? config.period : "daily";
    const [periodLabel, per, spentWhen] = AI_PERIOD[period] ?? [
      words(period),
      "",
      "",
    ];
    const cap = typeof config.cap_inr === "number" ? config.cap_inr : null;
    const spent = typeof status.spent_inr === "number" ? status.spent_inr : 0;
    const atCap = status.at_cap === true;
    const waiting = typeof status.waiting === "number" ? status.waiting : 0;
    const model = models
      .map((item) => read.object(item))
      .find((item) => item.model === config.model);
    const revision = typeof data.revision === "number" ? data.revision : null;
    const provider =
      typeof data.provider_label === "string"
        ? data.provider_label
        : "the AI provider";
    return {
      revision: revision !== null ? String(revision) : null,
      changedAt: (() => {
        const first = read.object(history[0]);
        return typeof first.at === "string" ? first.at : null;
      })(),
      rows: [
        {
          id: "lead_desk_ai.enabled",
          label: "AI replies to lead messages",
          value: yesNo(config.enabled, "On", "Off"),
          note: [
            provider,
            `${rupees(spent)} spent ${spentWhen}`.trim(),
            atCap ? "cap reached" : null,
            waiting ? `${waiting} waiting` : null,
          ]
            .filter(Boolean)
            .join(" · "),
        },
        {
          id: "lead_desk_ai.model",
          label: "AI replies: model",
          value:
            typeof model?.label === "string"
              ? model.label
              : typeof config.model === "string"
                ? config.model
                : "—",
        },
        {
          id: "lead_desk_ai.cap_inr",
          label: "AI replies: cap",
          value:
            cap === null
              ? "—"
              : `₹${cap.toLocaleString("en-IN")} ${per}`.trim(),
        },
        {
          id: "lead_desk_ai.period",
          label: "AI replies: cap counted",
          value: periodLabel,
        },
      ],
      ...(atCap || waiting
        ? {
            raise: {
              revision,
              to:
                typeof status.raise_to_inr === "number"
                  ? status.raise_to_inr
                  : (cap ?? 0) + 100,
              atCap,
              waiting,
            },
          }
        : {}),
    };
  });
}
