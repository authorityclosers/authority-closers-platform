import type { ReportEvidence } from "./report-contract";

/**
 * The analysis' own words for Dipak's six pillars (`report-pillars/1`, agreed
 * with H/1801 on 11 Oct). Optional and lenient: a part that does not check out
 * is dropped and the Report falls back to the older fields for it, so a
 * newer or partial projection can never stop a report from opening. Evidence
 * still goes through the report's strict quote-in-segment check.
 */

export type PillarNote = { text: string; evidence: ReportEvidence[] };

const OUTCOMES = [
  "Follow-up Set",
  "Decision Pending",
  "Deferred",
  "Meeting Booked",
  "Disqualified",
  "No Clear Next Step",
  "Still Open",
] as const;
export type PillarOutcome = (typeof OUTCOMES)[number];

const MOMENT_KINDS = [
  "Strong Moment",
  "Turning Point",
  "Buying Signal",
  "Important Miss",
  "Objection",
  "Price Moment",
  "Decision Moment",
  "Trust Moment",
  "Commitment",
  "Risk",
] as const;
export type PillarMomentKind = (typeof MOMENT_KINDS)[number];

const VALUE_CONNECTION = [
  "Established",
  "Partially established",
  "Not established",
] as const;
const QUALITY = ["Clear", "Soft", "Unclear"] as const;

export type ReportPillars = {
  version: "report-pillars/1";
  outcome?: {
    status: PillarOutcome;
    line: string | null;
    evidence: ReportEvidence[];
  };
  summary?: string;
  biggest_influence?: PillarNote;
  strongest_part?: PillarNote & { short: string | null };
  biggest_concern?: PillarNote & { short: string | null };
  next_step?: PillarNote & { when: string | null };
  timeline?: { label: string; start_ms: number }[];
  key_change?: {
    text: string;
    evidence: ReportEvidence[];
    before: { label: string | null; text: string };
    after: { label: string | null; text: string };
  };
  worked?: {
    title: string;
    what: string;
    evidence: ReportEvidence[];
    why_it_helped: string | null;
  }[];
  didnt?: {
    title: string;
    what: string;
    evidence: ReportEvidence[];
    what_it_affected: string | null;
    possible_areas: string[];
  }[];
  moments?: {
    kind: PillarMomentKind;
    title: string;
    evidence: ReportEvidence[];
    why: string | null;
    moved_toward: string | null;
    what_was_missed: string | null;
    price_stated: PillarNote | null;
    prospect_response: PillarNote | null;
  }[];
  deeper?: {
    became_clear: string[];
    still_unclear: string[];
    opening_missed: PillarNote | null;
    relevant: string[];
    less_relevant: string | null;
    value_connection: (typeof VALUE_CONNECTION)[number] | null;
    price: PillarNote | null;
    prospect_response: PillarNote | null;
    likely_status: string[];
    listening: string | null;
    communication_note: PillarNote | null;
  };
  deal?: {
    position: PillarNote | null;
    blocker: (PillarNote & { basis: "said" | "inferred" }) | null;
    prospect_commitments: PillarNote[];
    seller_commitments: PillarNote[];
    next_event: (PillarNote & { when: string | null }) | null;
    commitment_quality: (typeof QUALITY)[number] | null;
    still_unclear: string[];
    deal_action: string | null;
    coaching_mission: string | null;
  };
  most_important_moment?: number;
};

type Json = Record<string, unknown>;
type Evidence = (value: unknown, code: string) => ReportEvidence;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function str(value: unknown, max = 1_200): string | null {
  return typeof value === "string" && value.trim() && value.length <= max
    ? value.trim()
    : null;
}

function strings(value: unknown, limit = 8): string[] {
  return Array.isArray(value)
    ? value
        .map((item) => str(item, 400))
        .filter((item): item is string => item !== null)
        .slice(0, limit)
    : [];
}

function oneOf<T extends string>(
  value: unknown,
  allowed: readonly T[],
): T | null {
  return typeof value === "string" && allowed.includes(value as T)
    ? (value as T)
    : null;
}

/** Evidence that checks out; one bad quote drops only itself. */
function evidenceList(value: unknown, evidence: Evidence, code: string) {
  if (!Array.isArray(value)) return [];
  const result: ReportEvidence[] = [];
  value.slice(0, 4).forEach((item, index) => {
    try {
      result.push(evidence(item, `${code}_${index}`));
    } catch {
      // Not bound to this transcript: left out, never shown unchecked.
    }
  });
  return result;
}

function note(
  value: unknown,
  evidence: Evidence,
  code: string,
): PillarNote | null {
  if (typeof value === "string") {
    const text = str(value);
    return text ? { text, evidence: [] } : null;
  }
  if (!isObject(value)) return null;
  const text = str(value.text);
  return text
    ? { text, evidence: evidenceList(value.evidence, evidence, code) }
    : null;
}

function notes(value: unknown, evidence: Evidence, code: string, limit = 6) {
  return Array.isArray(value)
    ? value
        .slice(0, limit)
        .map((item, index) => note(item, evidence, `${code}_${index}`))
        .filter((item): item is PillarNote => item !== null)
    : [];
}

/** Each part on its own: one that fails is simply absent. */
function part<T>(read: () => T | null | undefined): T | undefined {
  try {
    return read() ?? undefined;
  } catch {
    return undefined;
  }
}

export function parseReportPillars(
  value: unknown,
  evidence: Evidence,
): ReportPillars | undefined {
  if (!isObject(value) || value.version !== "report-pillars/1")
    return undefined;
  const code = "report_pillars";
  const pillars: ReportPillars = { version: "report-pillars/1" };

  pillars.outcome = part(() => {
    const item = value.outcome;
    if (!isObject(item)) return null;
    const status = oneOf(item.status, OUTCOMES);
    return status
      ? {
          status,
          line: str(item.line),
          evidence: evidenceList(item.evidence, evidence, `${code}_outcome`),
        }
      : null;
  });
  pillars.summary = part(() => str(value.summary, 2_400));
  pillars.biggest_influence = part(() =>
    note(value.biggest_influence, evidence, `${code}_influence`),
  );
  for (const key of ["strongest_part", "biggest_concern"] as const)
    pillars[key] = part(() => {
      const base = note(value[key], evidence, `${code}_${key}`);
      const item = value[key];
      return base
        ? { ...base, short: isObject(item) ? str(item.short, 80) : null }
        : null;
    });
  pillars.next_step = part(() => {
    const base = note(value.next_step, evidence, `${code}_next_step`);
    const item = value.next_step;
    return base
      ? { ...base, when: isObject(item) ? str(item.when, 120) : null }
      : null;
  });
  pillars.timeline = part(() => {
    if (!Array.isArray(value.timeline)) return null;
    const stages = value.timeline
      .slice(0, 12)
      .map((item) =>
        isObject(item) &&
        Number.isSafeInteger(item.start_ms) &&
        (item.start_ms as number) >= 0
          ? { label: str(item.label, 48), start_ms: item.start_ms as number }
          : null,
      )
      .filter(
        (item): item is { label: string; start_ms: number } =>
          item !== null && item.label !== null,
      )
      .sort((a, b) => a.start_ms - b.start_ms);
    return stages.length ? stages : null;
  });
  pillars.key_change = part(() => {
    const item = value.key_change;
    if (!isObject(item)) return null;
    const side = (raw: unknown) =>
      isObject(raw) && str(raw.text)
        ? { label: str(raw.label, 48), text: str(raw.text)! }
        : null;
    const before = side(item.before);
    const after = side(item.after);
    const text = str(item.text);
    const refs = evidenceList(item.evidence, evidence, `${code}_change`);
    return text && before && after && refs.length
      ? { text, evidence: refs, before, after }
      : null;
  });
  pillars.worked = part(() =>
    Array.isArray(value.worked)
      ? value.worked
          .slice(0, 5)
          .map((item, index) =>
            isObject(item) && str(item.title, 200) && str(item.what)
              ? {
                  title: str(item.title, 200)!,
                  what: str(item.what)!,
                  evidence: evidenceList(
                    item.evidence,
                    evidence,
                    `${code}_worked_${index}`,
                  ),
                  why_it_helped: str(item.why_it_helped),
                }
              : null,
          )
          .filter((item) => item !== null)
      : null,
  );
  pillars.didnt = part(() =>
    Array.isArray(value.didnt)
      ? value.didnt
          .slice(0, 3)
          .map((item, index) =>
            isObject(item) && str(item.title, 200) && str(item.what)
              ? {
                  title: str(item.title, 200)!,
                  what: str(item.what)!,
                  evidence: evidenceList(
                    item.evidence,
                    evidence,
                    `${code}_didnt_${index}`,
                  ),
                  what_it_affected: str(item.what_it_affected),
                  possible_areas: strings(item.possible_areas),
                }
              : null,
          )
          .filter((item) => item !== null)
      : null,
  );
  pillars.moments = part(() =>
    Array.isArray(value.moments)
      ? value.moments
          .slice(0, 10)
          .map((item, index) => {
            if (!isObject(item)) return null;
            const kind = oneOf(item.kind, MOMENT_KINDS);
            const title = str(item.title, 200);
            const refs = evidenceList(
              item.evidence,
              evidence,
              `${code}_moment_${index}`,
            );
            // A moment is something to replay: no quote, no moment.
            if (!kind || !title || !refs.length) return null;
            return {
              kind,
              title,
              evidence: refs,
              why: str(item.why),
              moved_toward: str(item.moved_toward),
              what_was_missed: str(item.what_was_missed),
              price_stated: note(
                item.price_stated,
                evidence,
                `${code}_moment_${index}_price`,
              ),
              prospect_response: note(
                item.prospect_response,
                evidence,
                `${code}_moment_${index}_response`,
              ),
            };
          })
          .filter((item) => item !== null)
      : null,
  );
  pillars.deeper = part(() => {
    const item = value.deeper;
    if (!isObject(item)) return null;
    return {
      became_clear: strings(item.became_clear),
      still_unclear: strings(item.still_unclear),
      opening_missed: note(item.opening_missed, evidence, `${code}_opening`),
      relevant: strings(item.relevant),
      less_relevant: str(item.less_relevant),
      value_connection: oneOf(item.value_connection, VALUE_CONNECTION),
      price: note(item.price, evidence, `${code}_price`),
      prospect_response: note(
        item.prospect_response,
        evidence,
        `${code}_response`,
      ),
      likely_status: strings(item.likely_status),
      listening: str(item.listening),
      communication_note: note(
        item.communication_note,
        evidence,
        `${code}_communication`,
      ),
    };
  });
  pillars.deal = part(() => {
    const item = value.deal;
    if (!isObject(item)) return null;
    const blocker = note(item.blocker, evidence, `${code}_blocker`);
    const basis = isObject(item.blocker)
      ? oneOf(item.blocker.basis, ["said", "inferred"] as const)
      : null;
    const next = note(item.next_event, evidence, `${code}_next_event`);
    return {
      position: note(item.position, evidence, `${code}_position`),
      blocker: blocker ? { ...blocker, basis: basis ?? "inferred" } : null,
      prospect_commitments: notes(
        item.prospect_commitments,
        evidence,
        `${code}_prospect_commitment`,
      ),
      seller_commitments: notes(
        item.seller_commitments,
        evidence,
        `${code}_seller_commitment`,
      ),
      next_event: next
        ? {
            ...next,
            when: isObject(item.next_event)
              ? str(item.next_event.when, 120)
              : null,
          }
        : null,
      commitment_quality: oneOf(item.commitment_quality, QUALITY),
      still_unclear: strings(item.still_unclear, 6),
      deal_action: str(item.deal_action),
      coaching_mission: str(item.coaching_mission, 500),
    };
  });
  pillars.most_important_moment = part(() =>
    Number.isSafeInteger(value.most_important_moment) &&
    (value.most_important_moment as number) >= 0 &&
    (value.most_important_moment as number) < (pillars.moments?.length ?? 0)
      ? (value.most_important_moment as number)
      : null,
  );
  return pillars;
}
