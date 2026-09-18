import { describe, expect, it } from "vitest";
import {
  encodeConversationId,
  parseAcquisitionReport,
  parseJobResponse,
  parseSavedRecordings,
  parseTranscript,
  REPORT_REVIEW_STATUS,
  ReportContractError,
  type ReportCitation,
  type SalesReport,
} from "./report-contract";
import overviewFixture from "../tests/fixtures/dipak-overview.json";

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

function previewEnvelope() {
  const {
    report_sections: _sections,
    source_sha256,
    transcript_revision,
    source_label,
    review_status,
    ...content
  } = validReport();
  void _sections;
  content.strengths = ["First visible strength", "Second visible strength"].map(
    (title) => ({
      title,
      explanation: "A complete explanation.",
      evidence: [
        {
          segment_id: "s1",
          quote: "Let us agree on the next step.",
          start_ms: 1000,
          end_ms: 2200,
        },
      ],
    }),
  );
  const zero = { visible_count: 0, total_count: 0, hidden_count: 0 };
  return {
    schema: "ac.sales-xray.report-envelope/2",
    submission_id: "submission-1",
    recording_id: "recording-1",
    run_id: "run-1",
    source_sha256,
    transcript_revision,
    source_label,
    report: {
      schema: "ac.sales-xray.report-access/2",
      access: "guest_preview",
      review_status,
      numeric_publication: false,
      content: { ...content, next_action: null },
      sections: [],
      unlock: null,
      preview: {
        version: "guest-findings-v1",
        sections: {
          strengths: { visible_count: 2, total_count: 3, hidden_count: 1 },
          improvements: { ...zero },
          missed_opportunities: { ...zero },
          objection_analysis: { ...zero },
          closing_analysis: { ...zero },
          golden_moments: { ...zero },
          prospect_interpretations: { ...zero },
          rewatch: { ...zero },
          ethics_notes: { ...zero },
        },
      },
    },
  };
}
const expectedSubmission = {
  submissionId: "submission-1",
  recordingId: "recording-1",
};

describe("server-withheld guest report preview", () => {
  it("keeps complete source evidence and exact remaining counts without creating hidden findings", () => {
    const value = parseAcquisitionReport(
      previewEnvelope(),
      expectedSubmission,
      transcript,
    );
    expect(value.claimed).toBe(false);
    expect(value.report.strengths).toHaveLength(2);
    expect(value.report.preview?.sections.strengths.hidden_count).toBe(1);
    expect(value.report.strengths[0].evidence[0].quote).toBe(
      transcript.segments[0].text,
    );
    expect(value.report.report_sections).toEqual([]);
  });

  it.each([
    { visible_count: 1, total_count: 3, hidden_count: 2 },
    { visible_count: 2, total_count: 3, hidden_count: 2 },
    { visible_count: 2, total_count: 2, hidden_count: 0 },
    { visible_count: 2, total_count: 4, hidden_count: 2 },
    { visible_count: 2, total_count: 3, hidden_count: -1 },
    { visible_count: 2, total_count: 3, hidden_count: 1.5 },
  ])("rejects forged or inconsistent preview counts %j", (counts) => {
    const envelope = previewEnvelope();
    envelope.report.preview.sections.strengths = counts;
    expect(() =>
      parseAcquisitionReport(envelope, expectedSubmission, transcript),
    ).toThrow();
  });

  it("rejects unknown metadata, missing section counts and invented overview counts", () => {
    const unknown = previewEnvelope();
    Object.assign(unknown.report.preview, { hidden_findings: ["Not allowed"] });
    expect(() =>
      parseAcquisitionReport(unknown, expectedSubmission, transcript),
    ).toThrow("unknown_field");
    const missing = previewEnvelope();
    Reflect.deleteProperty(missing.report.preview.sections, "rewatch");
    expect(() =>
      parseAcquisitionReport(missing, expectedSubmission, transcript),
    ).toThrow();
    const invented = previewEnvelope();
    invented.report.preview.sections.golden_moments = {
      visible_count: 0,
      total_count: 1,
      hidden_count: 1,
    };
    expect(() =>
      parseAcquisitionReport(invented, expectedSubmission, transcript),
    ).toThrow("report_preview_count_mismatch");
  });

  it("keeps account reports complete and rejects a claimed projection carrying preview limits", () => {
    const envelope = previewEnvelope();
    envelope.report.access = "claimed_account";
    expect(() =>
      parseAcquisitionReport(envelope, expectedSubmission, transcript),
    ).toThrow("report_preview_account_invalid");
    Object.assign(envelope.report, { preview: null });
    envelope.report.content.strengths.push({
      ...envelope.report.content.strengths[0],
      title: "Third account strength",
    });
    const value = parseAcquisitionReport(
      envelope,
      expectedSubmission,
      transcript,
    );
    expect(value.claimed).toBe(true);
    expect(value.report.strengths).toHaveLength(3);
    expect(value.report.preview).toBeUndefined();
  });

  it("retains historical envelope compatibility without making up remaining counts", () => {
    const envelope = previewEnvelope();
    Reflect.deleteProperty(envelope.report, "preview");
    expect(
      parseAcquisitionReport(envelope, expectedSubmission, transcript).report
        .preview,
    ).toBeUndefined();
  });

  it("does not let preview metadata bypass quote or source validation", () => {
    const wrongQuote = previewEnvelope();
    wrongQuote.report.content.strengths[0].evidence[0].quote = "Invented words";
    expect(() =>
      parseAcquisitionReport(wrongQuote, expectedSubmission, transcript),
    ).toThrow("quote_mismatch");
    const wrongSource = previewEnvelope();
    wrongSource.source_sha256 = "ff".repeat(32);
    expect(() =>
      parseAcquisitionReport(wrongSource, expectedSubmission, transcript),
    ).toThrow("report_envelope_binding");
  });

  it("still rejects dangling overview references after projection", () => {
    const envelope = previewEnvelope();
    envelope.transcript_revision = overviewFixture.transcript.revision;
    const {
      report_sections: _sections,
      source_sha256: _source,
      transcript_revision: _revision,
      source_label: _label,
      review_status: _status,
      ...content
    } = overviewFixture.report;
    void [_sections, _source, _revision, _label, _status];
    Object.assign(envelope.report, { content, preview: null });
    Object.assign(envelope.report.content, {
      overview: {
        ...structuredClone(content.overview),
        golden_moments: [
          { ...content.overview.golden_moments[0], strength_index: 2 },
        ],
      },
    });
    expect(() =>
      parseAcquisitionReport(
        envelope,
        expectedSubmission,
        overviewFixture.transcript,
      ),
    ).toThrow("report_overview_invalid");
  });
});
