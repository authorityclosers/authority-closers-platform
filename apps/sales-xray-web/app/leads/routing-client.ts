/**
 * Routing rules (Lead OS, 27 Oct 2026; owner: lead rules "smarter, more
 * intelligent"): rules read top to bottom, and the first that fits a new lead
 * and has someone free gives it out, to one person or to a group in turn.
 * With no rule that fits, the lead rules share it fairly (fewest open leads
 * first). Owners and managers only; nothing is saved until Save.
 */

import { displayName, displayNameOf } from "../display-name";

const BASE = "/v1/lead-desk/routing-rules";

export type ConditionField =
  | "source"
  | "city"
  | "language"
  | "interest"
  | "answer"
  | "value";

export type Condition =
  | {
      field: "source" | "city" | "language" | "interest";
      values: string[];
    }
  | { field: "answer"; key: string; values: string[] }
  | {
      field: "value";
      /** At least needs low; below needs high; between both, low ≤ high (rupees). */
      op: "at_least" | "below" | "between";
      low: number | null;
      high: number | null;
    };

export type RoutingRule = {
  /** Null on a new rule: the server gives it one. */
  id: string | null;
  name: string;
  enabled: boolean;
  /** All of them must hold (1 to 6). */
  when: Condition[];
  /** One person, or a group taking turns (1 to 30). */
  give_to: string[];
};

export type RoutingPerson = Readonly<{
  person_id: string;
  name: string;
  available: boolean;
  open_leads: number;
  max_open: number | null;
}>;

export type FormQuestion = Readonly<{
  key: string;
  label: string;
  /** How many recent leads answered it. */
  answered: number;
  examples: string[];
}>;

export type Routing = Readonly<{
  schema: string;
  revision: number;
  can_edit: boolean;
  /** The form question whose answer is a lead's value, or null. */
  value_answer: string | null;
  rules: RoutingRule[];
  /** Source key → its words. */
  sources: Record<string, string>;
  people: RoutingPerson[];
  questions: FormQuestion[];
}>;

export type TryLead = {
  source?: string;
  city?: string;
  language?: string;
  interest?: string;
  value?: string;
  answers?: Record<string, string>;
};

export type TryResult = Readonly<{
  person_id: string | null;
  name: string | null;
  /** 1-based; null when no rule gave it out. */
  rule: number | null;
  rule_name: string | null;
  why: string;
  passed_over: string[];
}>;

export class RoutingError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "RoutingError";
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // No body: the status says enough.
    }
    throw new RoutingError(
      response.status === 409
        ? "Someone else saved the rules first. Your changes are still here: check them and save again."
        : (detail ?? "The rules weren't saved. Try again."),
      response.status,
    );
  }
  return (await response.json()) as T;
}

// People's names with capitals ("Priya Shah"); rule names stay as typed.
const named = (routing: Routing): Routing => ({
  ...routing,
  people: routing.people.map((person) => ({
    ...person,
    name: displayName(person.name),
  })),
});

export const readRouting = (signal?: AbortSignal) =>
  call<Routing>("", { signal }).then(named);

/** Replaces every rule at once and returns the same view. */
export const saveRouting = (
  revision: number,
  valueAnswer: string | null,
  rules: RoutingRule[],
) =>
  call<Routing>("", {
    method: "PUT",
    body: JSON.stringify({
      expected_revision: revision,
      value_answer: valueAnswer,
      rules,
    }),
  }).then(named);

/** Who a lead like this would go to now, and why. Nothing is saved. */
export const tryRouting = (lead: TryLead) =>
  call<TryResult>("/try", { method: "POST", body: JSON.stringify(lead) }).then(
    (result) => ({ ...result, name: displayNameOf(result.name) }),
  );

const RUPEES = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

/** "₹1,00,000". */
export const rupees = (amount: number) => RUPEES.format(amount);

/** A condition in plain words: "Source is Facebook and Instagram lead ads". */
export function conditionWords(
  condition: Condition,
  routing: Pick<Routing, "sources" | "questions">,
): string {
  const list = (values: string[]) =>
    values.length > 2
      ? `${values.slice(0, 2).join(", ")} or ${values.length - 2} more`
      : values.join(" or ");
  switch (condition.field) {
    case "source":
      return `Source is ${list(condition.values.map((value) => routing.sources[value] ?? value))}`;
    case "city":
      return `City is ${list(condition.values)}`;
    case "language":
      return `Speaks ${list(condition.values)}`;
    case "interest":
      return `Wants ${list(condition.values)}`;
    case "answer": {
      const question =
        routing.questions.find((item) => item.key === condition.key)?.label ??
        condition.key;
      return `“${question}” is ${list(condition.values)}`;
    }
    case "value":
      return condition.op === "at_least"
        ? `Value ${rupees(condition.low ?? 0)} or more`
        : condition.op === "below"
          ? `Value under ${rupees(condition.high ?? 0)}`
          : `Value ${rupees(condition.low ?? 0)} to ${rupees(condition.high ?? 0)}`;
  }
}

/** Whether a condition is complete enough to save. */
export function conditionReady(condition: Condition): boolean {
  if (condition.field === "value") {
    const { op, low, high } = condition;
    if (op === "at_least") return low !== null && low > 0;
    if (op === "below") return high !== null && high > 0;
    return low !== null && high !== null && low <= high && high > 0;
  }
  if (condition.field === "answer")
    return Boolean(condition.key) && condition.values.length > 0;
  return condition.values.length > 0;
}

/** Whether a rule can be saved: a name, 1 to 6 complete conditions, 1 to 30 people. */
export function ruleReady(rule: RoutingRule): boolean {
  return (
    rule.name.trim().length > 0 &&
    rule.when.length >= 1 &&
    rule.when.length <= 6 &&
    rule.when.every(conditionReady) &&
    rule.give_to.length >= 1 &&
    rule.give_to.length <= 30
  );
}
