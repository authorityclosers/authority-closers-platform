/**
 * Pure helpers for the lead screen's "From the calls" card: plain words for
 * each fact's basis and question, the quote's speaker and time, grouping, and
 * turning a seller's edit into the fact's typed value. No React, no fetch.
 */

import type { Evidence, Fact, Question } from "./call-data-client";

const ROLE: Record<Evidence["role"], string> = {
  prospect: "Prospect",
  salesperson: "You",
  other: "Someone else",
  unknown: "Speaker",
};

export function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function speakerLine(evidence: Evidence): string {
  return `${ROLE[evidence.role] ?? "Speaker"} · ${clock(evidence.start_ms)}`;
}

export function basisLabel(fact: Fact): string {
  if (fact.ai_read) return "AI read";
  if (fact.basis === "confirmed") return "You confirmed";
  if (fact.basis === "edited") return "You changed";
  if (fact.status === "auto_filled") return "Filled from the call";
  return "Heard in the call";
}

const FIELD: Record<string, string> = {
  name: "Name",
  company: "Company",
  city: "City",
  interest: "Interested in",
};

export function fieldLabel(field: string | null): string {
  return field ? (FIELD[field] ?? field) : "";
}

/** The one-line ask above the value. */
export function questionText(question: Question): string {
  if (question.question === "replace")
    return `The lead says “${question.lead_value ?? ""}”. Use what the call says?`;
  if (question.question === "fill")
    return `Add to the lead as ${fieldLabel(question.lead_field)}?`;
  return "Is this right?";
}

export function keepLabel(question: Question): string {
  return question.question === "replace" ? "Use the call’s" : "Yes, keep";
}

export function rejectLabel(question: Question): string {
  return question.question === "replace" ? "Keep the lead’s" : "Not right";
}

/** Facts grouped by category, in the taxonomy's order, empty groups left out. */
export function groupFacts(
  facts: Fact[],
  categories: Record<string, string>,
): { key: string; label: string; facts: Fact[] }[] {
  const order = Object.keys(categories);
  const groups = new Map<string, Fact[]>();
  for (const fact of facts) {
    const list = groups.get(fact.category) ?? [];
    list.push(fact);
    groups.set(fact.category, list);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b))
    .map(([key, list]) => ({
      key,
      label: categories[key] ?? key,
      facts: list,
    }));
}

const SCALE: [RegExp, number][] = [
  [/crore|cr\b/i, 10_000_000],
  [/lakh|lac|\bl\b/i, 100_000],
  [/\bk\b|thousand|hazaar|hazar/i, 1_000],
];

/** Numbers as said, e.g. "4-5 lakh a month" → 400000..500000, period month. */
export function numericFromText(
  text: string,
  previous: Record<string, unknown> = {},
): Record<string, unknown> | null {
  const numbers = [...text.replaceAll(",", "").matchAll(/\d+(?:\.\d+)?/g)].map(
    (match) => Number(match[0]),
  );
  if (!numbers.length || numbers.length > 2) return null;
  const scale = SCALE.find(([pattern]) => pattern.test(text))?.[1] ?? 1;
  const [low, high] = [numbers[0] * scale, (numbers[1] ?? numbers[0]) * scale];
  if (!Number.isFinite(low) || !Number.isFinite(high) || high < low)
    return null;
  const money =
    /₹|rs\.?\b|rupee|inr|lakh|lac|crore/i.test(text) ||
    previous.currency_code === "INR";
  const period = /month|mahina|\/m\b|pm\b/i.test(text)
    ? "month"
    : /year|saal|annual|pa\b/i.test(text)
      ? "year"
      : undefined;
  const value: Record<string, unknown> = {
    text,
    interval_shape: low === high ? "point" : "range",
    approximation: low === high ? "exact" : "approximate",
    lower: String(low),
    upper: String(high),
    lower_inclusive: true,
    upper_inclusive: true,
  };
  if (money) value.currency_code = "INR";
  else if (typeof previous.unit === "string") value.unit = previous.unit;
  if (period) value.period = period;
  return value;
}

/** The typed value a seller's edit becomes, keeping the fact's other parts. */
export function editedValue(
  fact: Fact,
  text: string,
): Record<string, unknown> | null {
  const said = text.trim();
  if (!said) return null;
  const previous = fact.value ?? {};
  switch (fact.kind) {
    case "numeric":
      return numericFromText(said, previous);
    case "person":
      return { ...previous, name: said };
    case "enum":
      return null; // chosen from a list, never typed
    case "when": {
      // A typed change replaces the words; the resolved date no longer applies.
      const rest: Record<string, unknown> = { ...previous };
      delete rest.date;
      delete rest.time;
      return { ...rest, text: said };
    }
    default:
      return { ...previous, text: said };
  }
}

/** What the edit box starts with. */
export function editStart(fact: Fact): string {
  const value = fact.value ?? {};
  if (fact.kind === "person" && typeof value.name === "string")
    return value.name;
  if (typeof value.text === "string") return value.text;
  return fact.display;
}
