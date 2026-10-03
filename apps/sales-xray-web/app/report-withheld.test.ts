import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { parseAcquisitionReport, parseTranscript } from "./report-contract";

const WITHHELD_MARKER = "[Withheld for privacy]";
const SOURCE_SHA256 = "a".repeat(64);
const RECORDING_ID = "11111111-1111-4111-8111-111111111111";

function fixture(name: string): unknown {
  return JSON.parse(
    readFileSync(
      resolve(process.cwd(), "../../tests/fixtures/sensitive_segments", name),
      "utf8",
    ),
  );
}

describe("withheld sensitive segments (AUT-521)", () => {
  it("parses the guarded transcript and report with the marker on both sides", () => {
    const transcript = parseTranscript(
      fixture("transcript.json"),
      SOURCE_SHA256,
    );
    const texts = Object.fromEntries(
      transcript.segments.map((segment) => [segment.id, segment.text]),
    );
    expect(texts.s3).toBe(WITHHELD_MARKER);
    expect(texts.s4).toBe(WITHHELD_MARKER);
    expect(texts.s9).not.toBe(WITHHELD_MARKER);
    expect(transcript.segments).toHaveLength(9);

    const { report, claimed } = parseAcquisitionReport(
      fixture("acquisition-report.json"),
      { submissionId: RECORDING_ID, recordingId: RECORDING_ID },
      transcript,
    );
    expect(claimed).toBe(true);
    const evidence = report.dimensions[1].evidence ?? [];
    expect(evidence.map((item) => item.segment_id)).toEqual(["s9", "s3", "s4"]);
    expect(evidence[1].quote).toBe(WITHHELD_MARKER);
    expect(evidence[2].quote).toBe(WITHHELD_MARKER);
    expect(evidence[0].quote).toBe(texts.s9);
    expect(report.dimensions[1].observation).toBe(WITHHELD_MARKER);
    expect(JSON.stringify(report)).not.toContain("purple otter");
  });
});
