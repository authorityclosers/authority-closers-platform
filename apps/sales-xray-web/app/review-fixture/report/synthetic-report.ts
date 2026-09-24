import baseFixture from "../../../tests/fixtures/dipak-overview.json";
import type {
  ReportDimension,
  ReportEvidence,
  SalesReport,
} from "../../report-contract";

// Invented dialogue for layout and interaction checks. No source recording exists.
export const syntheticEvidence = {
  concern: {
    segment_id: "synthetic-concern",
    quote: "Our timing is uncertain on this side.",
    start_ms: 12_000,
    end_ms: 15_000,
  },
  boundary: {
    segment_id: "synthetic-boundary",
    quote: "I don't want to set another step today. Please don't follow up.",
    start_ms: 26_000,
    end_ms: 30_000,
  },
  respect: {
    segment_id: "synthetic-respect",
    quote: "Understood. I won't schedule a follow-up.",
    start_ms: 31_000,
    end_ms: 35_000,
  },
} satisfies Record<string, ReportEvidence>;

const base = baseFixture.report as SalesReport;

const dimensions = [
  {
    ...base.dimensions[0],
    status: "observed",
    observation:
      "The seller acknowledged the buyer's boundary and did not imply an agreed follow-up.",
    citations: [],
    evidence: [syntheticEvidence.respect],
  },
  {
    ...base.dimensions[1],
    status: "observed",
    observation:
      "The buyer stated that timing was uncertain; the source does not establish why.",
    citations: [],
    evidence: [syntheticEvidence.concern],
  },
  {
    ...base.dimensions[2],
    status: "insufficient_evidence",
    observation:
      "This short synthetic exchange does not establish qualification details.",
    citations: [],
    evidence: [],
  },
  {
    ...base.dimensions[7],
    status: "unknown",
    observation:
      "No supported observation was supplied for the wider call's tonality.",
    citations: [],
  },
] satisfies Array<ReportDimension & { evidence?: ReportEvidence[] }>;

/** A small display fixture, never parsed as or promoted to a generated report. */
export const syntheticReport = {
  ...base,
  summary: "Synthetic call: the buyer declined a sale and a next step.",
  source_label: "Synthetic display only · no recording",
  transcript_revision: "synthetic-display-r1",
  strengths: [
    {
      title: "Respect the buyer's boundary",
      explanation:
        "The seller acknowledged the decline without implying that a follow-up was scheduled.",
      evidence: [syntheticEvidence.respect],
    },
  ],
  improvements: [
    {
      title: "Clarify timing earlier",
      explanation:
        "The buyer mentioned uncertain timing. A neutral question could have clarified the concern before the conversation ended.",
      evidence: [syntheticEvidence.concern],
    },
  ],
  missed_opportunities: [],
  objection_analysis: [],
  closing_analysis: [],
  verdict: "Synthetic display only. No next action was agreed in this example.",
  dimensions,
  overview: {
    ...base.overview!,
    outcome: {
      kind: "no_sale",
      text: "No sale was agreed. The buyer declined a next step and asked the seller not to follow up.",
      evidence: [syntheticEvidence.boundary],
    },
    next_call_focus: {
      improvement_index: 0,
      behavior:
        "In a future conversation, ask one neutral question about timing before offering a plan.",
      target:
        "Clarify the reason for uncertainty without assuming a follow-up is wanted.",
    },
    practice: {
      improvement_index: 0,
      instructions:
        "Rehearse a permission-based question, then accept a decline without pressing for a next step.",
      success_condition:
        "You ask once, listen, and leave the decision with the buyer.",
    },
  },
} satisfies SalesReport;
