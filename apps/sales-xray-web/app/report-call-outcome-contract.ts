export const CALL_OUTCOME_LABELS = {
  won: "Won",
  lost: "Lost",
  follow_up: "Follow-up",
  no_decision: "No decision",
} as const;
export type CallOutcomeKind = keyof typeof CALL_OUTCOME_LABELS;
export type HumanCallOutcome = {
  outcome: CallOutcomeKind;
  lost_reason: string | null;
  follow_up_on: string | null;
  deal_value: { amount: string; currency_code: string } | null;
};

/** Mirror the owner-approved human value boundary, not an AI extraction result. */
export function parseHumanCallOutcome(input: unknown): HumanCallOutcome {
  const invalid = (): never => {
    throw new Error("Enter a valid call outcome.");
  };
  if (!input || typeof input !== "object" || Array.isArray(input)) invalid();
  const row = input as Record<string, unknown>;
  if (
    typeof row.outcome !== "string" ||
    !Object.hasOwn(CALL_OUTCOME_LABELS, row.outcome) ||
    Object.keys(row).some(
      (key) =>
        !["outcome", "lost_reason", "follow_up_on", "deal_value"].includes(key),
    )
  )
    invalid();
  const reason = row.lost_reason ?? null;
  const date = row.follow_up_on ?? null;
  if (
    row.outcome === "lost"
      ? typeof reason !== "string" ||
        !reason.trim() ||
        reason.length > 1000 ||
        reason.includes("\0")
      : reason !== null
  )
    invalid();
  if (row.outcome === "follow_up") {
    if (
      typeof date !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      Number(date.slice(0, 4)) < 1 ||
      !Number.isFinite(Date.parse(date + "T00:00:00Z")) ||
      new Date(date + "T00:00:00Z").toISOString().slice(0, 10) !== date
    )
      invalid();
  } else if (date !== null) invalid();
  const value = row.deal_value ?? null;
  if (value !== null) {
    if (typeof value !== "object" || Array.isArray(value)) invalid();
    const amount = value as Record<string, unknown>;
    if (
      Object.keys(amount).length !== 2 ||
      typeof amount.amount !== "string" ||
      !/^(?:0|[1-9]\d{0,15})(?:\.\d{1,4})?$/.test(amount.amount) ||
      typeof amount.currency_code !== "string" ||
      !/^[A-Z]{3}$/.test(amount.currency_code)
    )
      invalid();
  }
  return {
    outcome: row.outcome as CallOutcomeKind,
    lost_reason: reason as string | null,
    follow_up_on: date as string | null,
    deal_value: value as HumanCallOutcome["deal_value"],
  };
}
