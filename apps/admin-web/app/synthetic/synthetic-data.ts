/** Normalizers for the read-only synthetic dataset browser. */
import { read } from "../lib/read";

export type SyntheticRow = {
  callId: string;
  businessId: string;
  repId: string | null;
  at: string | null;
  sequence: number | null;
  language: string | null;
  scenario: string | null;
  outcome: string | null;
  stage: string | null;
  dealValue: number | null;
  durationMs: number | null;
};
export type SyntheticFacet = { value: string; count: number };
export type SyntheticIndex = {
  label: string;
  total: number;
  datasetTotal: number;
  items: SyntheticRow[];
  nextOffset: number | null;
  facets: {
    businesses: SyntheticFacet[];
    languages: SyntheticFacet[];
    outcomes: SyntheticFacet[];
  };
};
export type SyntheticCall = {
  label: string;
  call: SyntheticRow;
  participants: { role: string; name: string }[];
  lines: {
    id: string;
    speaker: string;
    text: string;
    phase: string | null;
    startMs: number;
  }[];
  answerKey: Record<string, unknown> | null;
};

const LABEL =
  "Synthetic test data: fictional people and companies, never a real team.";

function row(raw: unknown): SyntheticRow {
  const body = read.object(raw);
  return {
    callId: read.string(body.call_id),
    businessId: read.string(body.business_id, "unknown"),
    repId: read.optionalString(body.rep_id),
    at: read.optionalString(body.at),
    sequence: read.optionalNumber(body.sequence),
    language: read.optionalString(body.language_mix),
    scenario: read.optionalString(body.scenario),
    outcome: read.optionalString(body.outcome),
    stage: read.optionalString(body.crm_stage),
    dealValue: read.optionalNumber(body.deal_value_inr),
    durationMs: read.optionalNumber(body.duration_ms),
  };
}
const facets = (raw: unknown): SyntheticFacet[] =>
  read.array(raw).map((item) => {
    const body = read.object(item);
    return { value: read.string(body.value), count: read.number(body.count) };
  });

export function normalizeSyntheticIndex(raw: unknown): SyntheticIndex {
  const body = read.object(raw);
  const facetBody = read.object(body.facets);
  return {
    label: read.string(body.label, LABEL),
    total: read.number(body.total),
    datasetTotal: read.number(body.dataset_total),
    items: read
      .array(body.items)
      .map(row)
      .filter((item) => item.callId),
    nextOffset: read.optionalNumber(body.next_offset),
    facets: {
      businesses: facets(facetBody.businesses),
      languages: facets(facetBody.languages),
      outcomes: facets(facetBody.outcomes),
    },
  };
}

export function normalizeSyntheticCall(raw: unknown): SyntheticCall {
  const body = read.object(raw);
  return {
    label: read.string(body.label, LABEL),
    call: row(body.call),
    participants: read.array(body.participants).map((item) => {
      const person = read.object(item);
      return {
        role: read.string(person.role, "other"),
        name: read.string(person.name, "Unnamed"),
      };
    }),
    lines: read.array(body.lines).map((item, index) => {
      const line = read.object(item);
      return {
        id: read.string(line.line_id, `line-${index}`),
        speaker: read.string(line.speaker, "other"),
        text: read.string(line.text),
        phase: read.optionalString(line.phase),
        startMs: read.number(line.start_ms),
      };
    }),
    answerKey:
      body.answer_key && typeof body.answer_key === "object"
        ? read.object(body.answer_key)
        : null,
  };
}

/** Keys that are bookkeeping, not content, in the answer key tree. */
export const QUIET_KEYS = new Set([
  "synthetic",
  "schema_version",
  "call_id",
  "line_ids",
  "timing_source",
  "playable",
]);

export const humanKey = (key: string) => {
  const text = key.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
};
