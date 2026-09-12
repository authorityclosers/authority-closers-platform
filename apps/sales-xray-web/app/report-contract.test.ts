import { describe, expect, it } from "vitest";
import {
  encodeConversationId,
  parseJobResponse,
  parseSavedRecordings,
  parseTranscript,
  REPORT_REVIEW_STATUS,
  ReportContractError,
  type ReportCitation,
  type SalesReport,
} from "./report-contract";

const sourceSha256 = "00".repeat(32);
const binding = { sourceSha256, durationMs: 4_000 };
const citation: ReportCitation = { doc: "Doc-1", sections: ["source section"] };
const transcript = {
  source_sha256: sourceSha256,
  revision: "scribe-test-r1",
  timebase_id: "1ms",
  duration_ms: 4_000,
  segments: [
    {
      id: "s1",
      speaker_id: "speaker-1",
      start_ms: 1_000,
      end_ms: 2_200,
      text: "Let us agree on the next step.",
    },
  ],
};

function validReport(): SalesReport {
  return {
    summary: "A source-bound draft.",
    strengths: [],
    missed_opportunities: [],
    improvements: [],
    objection_analysis: [],
    closing_analysis: [],
    verdict: "Try one clearer next step.",
    review_status: REPORT_REVIEW_STATUS,
    source_label: "Server-derived source-bound draft",
    source_sha256: sourceSha256,
    transcript_revision: "scribe-test-r1",
    dimensions: Array.from({ length: 8 }, (_, index) => ({
      dimension_id: `dimension-${index + 1}`,
      label: `Dimension ${index + 1}`,
      status: "unknown",
      observation: "Insufficient evidence.",
      citations: [citation],
    })),
    report_sections: Array.from({ length: 9 }, (_, index) => ({
      number: index + 1,
      title: `Report section ${index + 1}`,
      required: "Keep this grounded in the call.",
      citations: [citation],
    })),
  };
}

function job(report: unknown = validReport()) {
  return {
    id: "run-1",
    state: "completed",
    message: "Report ready.",
    report,
  };
}

describe("CallStudio report contract", () => {
  it("normalizes a strict report without practice or model review text", () => {
    const parsed = parseJobResponse(job(), binding);
    expect(parsed.report?.review_status).toBe(REPORT_REVIEW_STATUS);
    expect(parsed.report?.strengths).toEqual([]);
    expect(parsed.report?.source_sha256).toBe(sourceSha256);
  });

  it("rejects a report whose source hash differs from the selected file", () => {
    expect(() =>
      parseJobResponse(
        job({ ...validReport(), source_sha256: "11".repeat(32) }),
        binding,
      ),
    ).toThrowError(new ReportContractError("report_source_mismatch"));
  });

  it("rejects evidence outside the selected recording duration", () => {
    const report = validReport();
    report.strengths = [
      {
        title: "Late evidence",
        explanation: "This should not render.",
        evidence: [
          {
            segment_id: "s1",
            quote: "outside the file",
            start_ms: 3_900,
            end_ms: 4_001,
          },
        ],
      },
    ];
    expect(() => parseJobResponse(job(report), binding)).toThrow(
      "report_strength_0_evidence_0_end_ms_out_of_range",
    );
  });

  it("rejects unknown fields and a provider supplied review status", () => {
    expect(() =>
      parseJobResponse(job({ ...validReport(), extra: "untrusted" }), binding),
    ).toThrow("report_unknown_field");
    expect(() =>
      parseJobResponse(
        job({ ...validReport(), review_status: "approved" }),
        binding,
      ),
    ).toThrow("report_review_status_invalid");
  });

  it("binds report evidence to the native transcript span and revision", () => {
    const report = validReport();
    report.strengths = [
      {
        title: "A clear next step",
        explanation: "The seller named the next step.",
        evidence: [
          {
            segment_id: "s1",
            quote: "agree on the next step",
            start_ms: 1_100,
            end_ms: 2_000,
          },
        ],
      },
    ];
    const parsed = parseJobResponse(job(report), {
      sourceSha256,
      durationMs: transcript.duration_ms,
      transcript: parseTranscript(transcript, sourceSha256),
    });
    expect(parsed.report?.transcript_revision).toBe("scribe-test-r1");

    expect(() =>
      parseJobResponse(
        job({
          ...report,
          strengths: [
            {
              ...report.strengths[0],
              evidence: [
                {
                  ...report.strengths[0].evidence[0],
                  quote: "not in the native segment",
                },
              ],
            },
          ],
        }),
        {
          sourceSha256,
          durationMs: transcript.duration_ms,
          transcript: parseTranscript(transcript, sourceSha256),
        },
      ),
    ).toThrow("report_strength_0_evidence_0_quote_mismatch");
  });

  it("parses bounded saved recordings and rejects unsafe path IDs", () => {
    const parsed = parseSavedRecordings({
      recordings: [
        {
          id: "recording-1",
          state: "completed",
          source_revision: "source-1",
          source_sha256: sourceSha256,
          source_bytes: 128,
          content_type: "audio/wav",
          created_at: "2026-09-13T00:00:00Z",
          latest_run: {
            id: "run-1",
            state: "completed",
            recipe_revision: "recipe-1",
            provider_calls: 0,
            has_report: true,
          },
          has_report: true,
        },
      ],
    });
    expect(parsed.recordings[0]?.latest_run?.has_report).toBe(true);
    expect(encodeConversationId("recording-1", "recording_id")).toBe(
      "recording-1",
    );
    expect(() => encodeConversationId("../../other", "recording_id")).toThrow(
      "recording_id_invalid",
    );
  });
});
