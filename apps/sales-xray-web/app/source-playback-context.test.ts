import { describe, expect, it } from "vitest";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
  TranscriptSegment,
} from "./report-contract";
import {
  buildContextualSourcePlayback,
  revalidateContextualSourcePlayback,
} from "./source-playback-context";

const sourceSha = "a1".repeat(32);
const savedEvidence: ReportEvidence = {
  segment_id: "s2",
  quote: "15,20",
  start_ms: 693_176,
  end_ms: 693_976,
};

function segment(
  id: string,
  speaker_id: string | null,
  start_ms: number,
  end_ms: number,
  text: string,
): TranscriptSegment {
  return { id, speaker_id, start_ms, end_ms, text };
}

function pair(
  segments: TranscriptSegment[] = [
    segment("s1", "speaker-1", 660_000, 692_896, "How much is stuck?"),
    segment("s2", "speaker-2", 693_176, 693_976, "15,20"),
    segment("s3", "speaker-1", 693_996, 700_376, "Fifteen to twenty lakh."),
    segment("s4", "speaker-2", 701_000, 702_000, "And then another turn."),
  ],
) {
  const report: SalesReport = {
    summary: "Saved summary.",
    strengths: [],
    missed_opportunities: [],
    improvements: [
      {
        title: "Review the capital question",
        explanation: "Saved explanation.",
        evidence: [{ ...savedEvidence }],
      },
    ],
    objection_analysis: [],
    closing_analysis: [],
    verdict: "Saved verdict.",
    review_status: "draft_not_dipak_adjudicated",
    source_label: "Fictional test",
    source_sha256: sourceSha,
    transcript_revision: "transcript-r1",
    dimensions: [],
    report_sections: [],
  };
  const transcript: Transcript = {
    source_sha256: sourceSha,
    revision: "transcript-r1",
    timebase_id: "decoded-audio-ms-v1",
    duration_ms: 800_000,
    segments,
  };
  return { report, transcript };
}

describe("source-bound adjacent transcript context", () => {
  it("keeps the saved sub-second numeric evidence intact and adds only immediate context", () => {
    const { report, transcript } = pair();
    const original = structuredClone(savedEvidence);
    const selection = buildContextualSourcePlayback(
      report,
      transcript,
      savedEvidence,
    );
    expect(selection).not.toBeNull();
    expect(selection?.evidence).toEqual(original);
    expect(selection?.context_before?.id).toBe("s1");
    expect(selection?.context_after?.id).toBe("s3");
    expect(selection?.context_before?.speaker_id).toBe("speaker-1");
    expect(selection?.evidence_speaker_id).toBe("speaker-2");
    expect(selection?.context_after?.text).toBe("Fifteen to twenty lakh.");
    expect(selection?.playback_range).toEqual({
      start_ms: 660_000,
      end_ms: 700_376,
    });
    expect(savedEvidence).toEqual(original);
    expect(report.improvements[0].evidence[0]).toEqual(original);
  });

  it("uses no more than one adjacent segment even when neighbors are long", () => {
    const { report, transcript } = pair([
      segment("s0", "speaker-1", 1_000, 40_000, "Earlier turn."),
      segment("s1", "speaker-1", 40_100, 692_900, "One long adjacent turn."),
      segment("s2", "speaker-2", 693_176, 693_976, "15,20"),
      segment("s3", "speaker-1", 693_996, 750_000, "Long answer."),
      segment("s4", "speaker-1", 750_100, 790_000, "Later turn."),
    ]);
    const selection = buildContextualSourcePlayback(
      report,
      transcript,
      savedEvidence,
    );
    expect(selection?.context_before?.id).toBe("s1");
    expect(selection?.context_after?.id).toBe("s3");
    expect(selection?.playback_range).toEqual({
      start_ms: 40_100,
      end_ms: 750_000,
    });
  });

  it("supports first and last source segments without inventing a missing neighbor", () => {
    const { report, transcript } = pair([
      segment("s2", null, 693_176, 693_976, "15,20"),
    ]);
    const firstOrLast = buildContextualSourcePlayback(
      report,
      transcript,
      savedEvidence,
    );
    expect(firstOrLast?.context_before).toBeNull();
    expect(firstOrLast?.context_after).toBeNull();
    expect(firstOrLast?.playback_range).toEqual({
      start_ms: savedEvidence.start_ms,
      end_ms: savedEvidence.end_ms,
    });
  });

  it("fails closed for source, revision, segment, or quote mismatches", () => {
    const { report, transcript } = pair();
    expect(
      buildContextualSourcePlayback(
        report,
        {
          ...transcript,
          source_sha256: "b2".repeat(32),
        },
        savedEvidence,
      ),
    ).toBeNull();
    expect(
      buildContextualSourcePlayback(
        report,
        {
          ...transcript,
          revision: "stale-r0",
        },
        savedEvidence,
      ),
    ).toBeNull();
    expect(
      buildContextualSourcePlayback(report, transcript, {
        ...savedEvidence,
        segment_id: "deleted-segment",
      }),
    ).toBeNull();
    expect(
      buildContextualSourcePlayback(report, transcript, {
        ...savedEvidence,
        quote: "not in the source segment",
      }),
    ).toBeNull();
  });

  it("revalidates exact report membership, context identity, and playback range", () => {
    const { report, transcript } = pair();
    const selection = buildContextualSourcePlayback(
      report,
      transcript,
      savedEvidence,
    )!;
    expect(
      revalidateContextualSourcePlayback(selection, report, transcript),
    ).toEqual(selection);
    expect(
      revalidateContextualSourcePlayback(
        { ...selection, playback_range: { start_ms: 0, end_ms: 800_000 } },
        report,
        transcript,
      ),
    ).toBeNull();
    expect(
      revalidateContextualSourcePlayback(
        { ...selection, context_after: null },
        report,
        transcript,
      ),
    ).toBeNull();

    const deleted = structuredClone(report);
    deleted.improvements = [];
    expect(
      revalidateContextualSourcePlayback(selection, deleted, transcript),
    ).toBeNull();
    expect(
      revalidateContextualSourcePlayback(selection, report, {
        ...transcript,
        revision: "transcript-r2",
      }),
    ).toBeNull();
  });

  it("omits an out-of-order immediate segment rather than crossing it", () => {
    const { report, transcript } = pair([
      segment("s1", "speaker-1", 694_000, 695_000, "Out of order."),
      segment("s2", "speaker-2", 693_176, 693_976, "15,20"),
      segment("s3", "speaker-1", 693_996, 700_376, "Fifteen to twenty lakh."),
    ]);
    const selection = buildContextualSourcePlayback(
      report,
      transcript,
      savedEvidence,
    );
    expect(selection?.context_before).toBeNull();
    expect(selection?.context_after?.id).toBe("s3");
  });
});
