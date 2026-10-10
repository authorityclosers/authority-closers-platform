/** PR #414's append-only profile read contract. No client extraction or merging. */
export const PROSPECT_FIELD_LABELS = {
  name: "Name",
  role: "Role",
  business: "Company",
  industry: "Industry",
  city: "City",
  team_size: "Team size",
  turnover: "Turnover",
  main_pain: "Main problem",
  budget: "Budget discussed",
  timeline: "Timeline",
  decision_maker: "Decision-maker",
  next_step: "Next step",
  phone: "Phone",
  email: "Email",
} as const;
export type ProfileKey = keyof typeof PROSPECT_FIELD_LABELS;
export type FactLabel =
  | "Observed"
  | "Inferred"
  | "Unknown"
  | "Changed"
  | "Contradiction";
export type ProfileValue =
  | { kind: "text"; text: string }
  | { kind: "numeric"; [key: string]: string | boolean | null | undefined };
export type ProfileEvidence = {
  submission_id: string;
  segment_id: string;
  quote: string;
  start_ms: number;
  end_ms: number;
};
export type ProfileField =
  | { state: "unknown"; reason: "not_asked" | "not_mentioned" }
  | {
      state: "known";
      value: ProfileValue;
      basis: "person" | "heard_in_call";
      locked: boolean;
      set_at: string;
      evidence?: ProfileEvidence;
      /** Optional read extension; supplied from append-only history, never inferred. */
      changed_from?: {
        value: ProfileValue;
        evidence: ProfileEvidence;
        set_at: string;
      };
      heard_differently?: {
        value: ProfileValue;
        evidence: ProfileEvidence;
        set_at: string;
      }[];
    };
export type ProfileFields = Partial<Record<ProfileKey, ProfileField>>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function check(condition: unknown): asserts condition {
  if (!condition) throw new Error("prospect_profile_invalid");
}
function record(value: unknown): Record<string, unknown> {
  check(value && typeof value === "object" && !Array.isArray(value));
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 2048): string {
  check(typeof value === "string" && value.trim() && value.length <= max);
  return value;
}
function value(input: unknown, key: ProfileKey): ProfileValue {
  const item = record(input);
  if (item.kind === "text") {
    check(Object.keys(item).length === 2);
    return {
      kind: "text",
      text: text(
        item.text,
        key === "name" || key === "phone" ? 160 : key === "email" ? 320 : 2048,
      ),
    };
  }
  check(item.kind === "numeric");
  check(["team_size", "turnover", "budget"].includes(key));
  const allowed = [
    "kind",
    "interval_shape",
    "approximation",
    "lower",
    "upper",
    "lower_inclusive",
    "upper_inclusive",
    "currency_code",
    "unit",
    "scale_as_stated",
    "period",
    "period_reference",
    "component",
    "cadence",
    "tax_treatment",
  ];
  check(Object.keys(item).every((k) => allowed.includes(k)));
  check(
    ["point", "range", "lower_bound", "upper_bound", "unknown"].includes(
      String(item.interval_shape),
    ),
  );
  check(
    ["exact", "approximate", "unknown"].includes(String(item.approximation)),
  );
  for (const [key, v] of Object.entries(item))
    check(
      v === null ||
        (typeof v === "boolean" &&
          ["lower_inclusive", "upper_inclusive"].includes(key)) ||
        (typeof v === "string" && v.length <= 2048),
    );
  for (const key of ["lower", "upper"])
    check(
      item[key] === null ||
        item[key] === undefined ||
        (typeof item[key] === "string" &&
          /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(
            item[key] as string,
          )),
    );
  for (const key of ["lower_inclusive", "upper_inclusive"])
    check(item[key] == null || typeof item[key] === "boolean");
  const lower = item.lower != null,
    upper = item.upper != null;
  const li = typeof item.lower_inclusive === "boolean",
    ui = typeof item.upper_inclusive === "boolean";
  check(
    item.interval_shape === "point" || item.interval_shape === "range"
      ? lower && upper && li && ui
      : item.interval_shape === "lower_bound"
        ? lower && !upper && li && !ui
        : item.interval_shape === "upper_bound"
          ? !lower && upper && !li && ui
          : !lower && !upper && !li && !ui,
  );
  check(
    !item.currency_code ||
      (typeof item.currency_code === "string" &&
        /^[A-Z]{3}$/.test(item.currency_code) &&
        !item.unit),
  );
  return { ...item } as ProfileValue;
}
function evidence(input: unknown): ProfileEvidence {
  const item = record(input);
  const submission = text(item.submission_id, 36);
  check(UUID.test(submission));
  check(
    Number.isSafeInteger(item.start_ms) &&
      Number.isSafeInteger(item.end_ms) &&
      (item.start_ms as number) >= 0 &&
      (item.end_ms as number) > (item.start_ms as number),
  );
  return {
    submission_id: submission,
    segment_id: text(item.segment_id, 128),
    quote: text(item.quote),
    start_ms: item.start_ms as number,
    end_ms: item.end_ms as number,
  };
}
export function parseProfileFields(input: unknown): ProfileFields {
  const items = record(input);
  const result: ProfileFields = {};
  check(Object.keys(items).length <= 14);
  for (const [rawKey, raw] of Object.entries(items)) {
    check(Object.hasOwn(PROSPECT_FIELD_LABELS, rawKey));
    const key = rawKey as ProfileKey;
    const field = record(raw);
    if (field.state === "unknown") {
      check(field.reason === "not_asked" || field.reason === "not_mentioned");
      result[key] = { state: "unknown", reason: field.reason };
      continue;
    }
    check(
      field.state === "known" &&
        (field.basis === "person" || field.basis === "heard_in_call"),
    );
    check(field.locked === (field.basis === "person"));
    check(!["phone", "email"].includes(key) || field.basis === "person");
    const parsed: Extract<ProfileField, { state: "known" }> = {
      state: "known",
      value: value(field.value, key),
      basis: field.basis,
      locked: field.locked as boolean,
      set_at: text(field.set_at, 80),
    };
    if (field.basis === "heard_in_call")
      parsed.evidence = evidence(field.evidence);
    if (field.changed_from !== undefined) {
      check(
        field.basis === "heard_in_call" && !["phone", "email"].includes(key),
      );
      const before = record(field.changed_from);
      const previousTime = text(before.set_at, 80);
      check(
        Number.isFinite(Date.parse(previousTime)) &&
          Date.parse(previousTime) < Date.parse(parsed.set_at),
      );
      parsed.changed_from = {
        value: value(before.value, key),
        evidence: evidence(before.evidence),
        set_at: previousTime,
      };
      check(
        JSON.stringify(parsed.changed_from.value) !==
          JSON.stringify(parsed.value),
      );
    }
    if (field.heard_differently !== undefined) {
      check(
        field.basis === "person" &&
          !["phone", "email"].includes(key) &&
          Array.isArray(field.heard_differently),
      );
      parsed.heard_differently = field.heard_differently.map((raw) => {
        const item = record(raw);
        return {
          value: value(item.value, key),
          evidence: evidence(item.evidence),
          set_at: text(item.set_at, 80),
        };
      });
    }
    result[key] = parsed;
  }
  return result;
}

/** Keep supplied bounds, approximation, units and scale; never convert money. */
export function profileValueText(value: ProfileValue): string {
  if (value.kind === "text") return value.text;
  const lower = value.lower,
    upper = value.upper;
  const bounds =
    value.interval_shape === "point"
      ? lower
      : value.interval_shape === "range"
        ? `${value.lower_inclusive ? "[" : "("}${lower}–${upper}${value.upper_inclusive ? "]" : ")"}`
        : value.interval_shape === "lower_bound"
          ? `${value.lower_inclusive ? "≥" : ">"} ${lower}`
          : value.interval_shape === "upper_bound"
            ? `${value.upper_inclusive ? "≤" : "<"} ${upper}`
            : "Unknown amount";
  return [
    value.approximation === "approximate" ? "Approximately" : null,
    bounds,
    value.scale_as_stated,
    value.currency_code ?? value.unit,
    value.period ? `per ${value.period}` : null,
    value.period_reference,
    value.component,
    value.cadence,
    value.tax_treatment,
  ]
    .filter((v) => v !== null && v !== undefined)
    .join(" ");
}
