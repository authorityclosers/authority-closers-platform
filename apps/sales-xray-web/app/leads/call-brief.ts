/**
 * The last analysed call on a lead in three short lines (UX study item 10,
 * 18 Oct, like Gong's call brief): what happened, the main objection and the
 * agreed next step, read leniently from the call's Report. Reports of
 * different ages carry different parts, so each line falls back in order and
 * a line with nothing behind it is left out; nothing is guessed.
 */

export type CallBrief = {
  /** What happened, in one or two sentences. */
  summary: string | null;
  /** The main objection or why it was lost. */
  objection: string | null;
  /** The agreed next step; `at` only when the Report names a date. */
  next: { text: string; at: Date | null } | null;
  /** The recorded outcome word (Lost, Follow-up Set, ...). */
  outcome: string | null;
};

type Bag = Record<string, unknown>;

const bag = (value: unknown): Bag =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Bag)
    : {};

function words(value: unknown, max = 220): string | null {
  if (typeof value !== "string") return null;
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) return null;
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/** The first one or two sentences, without a test-data preamble. */
function opening(value: unknown): string | null {
  const text = words(value, 2000)?.replace(/^Synthetic test call\.\s*/i, "");
  if (!text) return null;
  const sentences = text.match(/[^.!?]+[.!?]+(\s|$)/g) ?? [text];
  let out = "";
  for (const [index, sentence] of sentences.entries()) {
    if (index >= 2 || (out && (out + sentence).length > 200)) break;
    out += sentence;
  }
  return words(out || text, 220);
}

/** A plain YYYY-MM-DD from the Report becomes 10:00 that day, local time. */
function dayAt(value: unknown, now: Date): Date | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const at = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    10,
    0,
    0,
    0,
  );
  return Number.isNaN(at.getTime()) || at.getTime() < now.getTime() ? null : at;
}

function first(list: unknown): Bag | null {
  return Array.isArray(list) && list.length ? bag(list[0]) : null;
}

/** Reads GET /submissions/{id}/report: { report: { content: … } }. */
export function callBrief(
  payload: unknown,
  now: Date = new Date(),
): CallBrief | null {
  const outer = bag(payload);
  const content = bag(bag(outer.report).content ?? outer.content);
  const structure = bag(content.structure);
  const final = bag(structure.final_call_outcome);
  const pillars = bag(content.pillars);
  const concern = bag(pillars.biggest_concern);
  const step = bag(pillars.next_step);
  const outcome = words(final.outcome, 40);

  const summary =
    opening(bag(structure.overview).summary) ??
    opening(pillars.summary) ??
    opening(content.summary);

  const objection =
    words(first(final.objections)?.text) ??
    words(concern.short) ??
    words(concern.text) ??
    words(first(content.objection_analysis)?.title) ??
    (outcome && /lost/i.test(outcome) ? words(final.lost_reason) : null);

  const at = dayAt(final.follow_up_on, now);
  const stepText =
    words(first(final.next_steps)?.text) ??
    words(step.text) ??
    (at ? "Follow up" : null);
  const when = words(first(final.next_steps)?.when, 60) ?? words(step.when, 60);
  const next = stepText
    ? { text: when ? `${stepText} (${when})` : stepText, at }
    : null;

  if (!summary && !objection && !next) return null;
  return { summary, objection, next, outcome };
}
