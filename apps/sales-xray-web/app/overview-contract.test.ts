import { expect, it } from "vitest";
import fixture from "../tests/fixtures/dipak-overview.json";
import { parseJobResponse, ReportContractError } from "./report-contract";

const binding = {
  sourceSha256: fixture.transcript.source_sha256,
  durationMs: fixture.transcript.duration_ms,
  transcript: fixture.transcript,
};
function parse(report: unknown) {
  return parseJobResponse(
    { id: "synthetic-run", state: "completed", message: "Ready", report },
    binding,
  ).report!;
}

it("reads the same complete synthetic overview validated by the Python parser", () => {
  const parsed = parse(fixture.report);
  expect(parsed.overview).toEqual(fixture.report.overview);
  expect(parsed.overview?.diagnosis?.evidence[0].quote).toBe(
    "Sure, which time works for you?",
  );
  expect(parsed.overview?.progress).toBeNull();
});

it("accepts the optional canonical top-level business impact projection", () => {
  const objectValue = structuredClone(fixture.report);
  Object.assign(objectValue.overview, {
    business_impact: {
      status: "insufficient_data",
      missing_inputs: ["No validated outcome or value data."],
    },
  });
  expect(parse(objectValue).overview?.business_impact).toEqual({
    status: "insufficient_data",
    missing_inputs: ["No validated outcome or value data."],
  });

  const nullableValue = structuredClone(fixture.report);
  Object.assign(nullableValue.overview, { business_impact: null });
  expect(parse(nullableValue).overview?.business_impact).toBeNull();
});

it.each([
  [
    "unknown field",
    (impact: Record<string, unknown>) => {
      impact.estimate = 5000;
    },
  ],
  [
    "unsupported status",
    (impact: Record<string, unknown>) => {
      impact.status = "validated";
    },
  ],
  [
    "empty missing inputs",
    (impact: Record<string, unknown>) => {
      impact.missing_inputs = [];
    },
  ],
] as const)("rejects malformed top-level business impact: %s", (_, mutate) => {
  const report = structuredClone(fixture.report);
  const impact = {
    status: "insufficient_data",
    missing_inputs: ["No validated outcome or value data."],
  } as Record<string, unknown>;
  mutate(impact);
  Object.assign(report.overview, { business_impact: impact });
  expect(() => parse(report)).toThrow(ReportContractError);
});

it("keeps legacy report bytes compatible without fabricating detailed fields", () => {
  const { overview: omitted, ...legacy } = fixture.report;
  expect(omitted.version).toBe("dipak-14-point-v1");
  expect(parse(legacy)).toEqual(legacy);
});

it.each([
  [
    "unknown version",
    (o: Record<string, unknown>) => {
      o.version = "unvalidated-v2";
    },
  ],
  [
    "history",
    (o: Record<string, unknown>) => {
      o.progress = { trend: "improving" };
    },
  ],
  [
    "numeric publication",
    (o: Record<string, unknown>) => {
      o.overall_score = 95;
    },
  ],
  [
    "missing field",
    (o: Record<string, unknown>) => {
      delete o.practice;
    },
  ],
  [
    "missing strength context",
    (o: Record<string, unknown>) => {
      o.strength_details = [];
    },
  ],
  [
    "unsupported golden moment",
    (o: Record<string, unknown>) => {
      o.golden_moments = [
        { strength_index: 2, evidence_index: 0, why_effective: "Unsupported" },
      ];
    },
  ],
  [
    "missing drill",
    (o: Record<string, unknown>) => {
      o.practice = null;
    },
  ],
  [
    "boolean focus index",
    (o: Record<string, unknown>) => {
      o.next_call_focus = {
        improvement_index: false,
        behavior: "Ask",
        target: "One question",
      };
    },
  ],
] as const)("rejects %s", (_, mutate) => {
  const report = structuredClone(fixture.report);
  mutate(report.overview);
  expect(() => parse(report)).toThrow(ReportContractError);
});

it("rejects modified nested quotations, fabricated subsegment timing and reordered changes", () => {
  const quote = structuredClone(fixture.report);
  quote.overview.diagnosis.evidence[0].quote = "invented";
  expect(() => parse(quote)).toThrow(/quote_mismatch/);
  const timing = structuredClone(fixture.report);
  timing.overview.diagnosis.evidence[0].start_ms += 1;
  expect(() => parse(timing)).toThrow(/timing_mismatch/);
  const order = structuredClone(fixture.report);
  order.overview.conversation_change.after =
    order.overview.conversation_change.before;
  expect(() => parse(order)).toThrow(/overview_invalid/);
});

it("rejects duplicate clips, financial expansion, and inferred concerns labeled as fact", () => {
  const duplicates = structuredClone(fixture.report);
  duplicates.overview.rewatch.push(duplicates.overview.rewatch[0]);
  expect(() => parse(duplicates)).toThrow(ReportContractError);
  const financial = structuredClone(fixture.report);
  Object.assign(financial.overview.improvement_details[0].business_impact, {
    estimate: 5000,
  });
  expect(() => parse(financial)).toThrow(ReportContractError);
  const concern = structuredClone(fixture.report);
  concern.overview.prospect_interpretations[0].interpretation_kind = "fact";
  expect(() => parse(concern)).toThrow(ReportContractError);
});
