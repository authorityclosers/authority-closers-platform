import { afterEach, describe, expect, it } from "vitest";
import { parseAcquisitionReport, parseTranscript } from "./report-contract";
import {
  parseAllowance,
  parseEntry,
  parsePolicy,
  parseProgress,
  parseSubmission,
  rememberSubmission,
  savedSubmissionId,
} from "./acquisition-client";
import {
  allowance,
  entry,
  envelope,
  policy,
  progress,
  submissionId,
  recordingId,
  transcript,
} from "../tests/acquisition-fixture";

afterEach(() => localStorage.clear());
describe("acquisition source-bound presentation", () => {
  it("preserves the full overview and mixed-script evidence through the v2 projection", () => {
    const parsed = parseAcquisitionReport(
      envelope,
      { submissionId, recordingId },
      parseTranscript(transcript, transcript.source_sha256),
    );
    expect(parsed.claimed).toBe(false);
    expect(parsed.report.overview).toEqual(envelope.report.content.overview);
    expect(parsed.report.report_sections).toEqual([]);
    expect(parsed.report.strengths).toEqual(envelope.report.content.strengths);
  });
  it.each([
    "source",
    "recording",
    "submission",
    "transcript",
    "numeric",
    "quote",
  ])("rejects a mismatched %s without presenting a report", (kind) => {
    const value = structuredClone(envelope);
    if (kind === "source") value.source_sha256 = "a".repeat(64);
    if (kind === "recording") value.recording_id = submissionId;
    if (kind === "submission") value.submission_id = recordingId;
    if (kind === "transcript") value.transcript_revision = "another-revision";
    if (kind === "numeric") value.report.numeric_publication = true;
    if (kind === "quote")
      value.report.content.strengths[0].evidence[0].quote =
        "An invented quotation";
    expect(() =>
      parseAcquisitionReport(
        value,
        { submissionId, recordingId },
        parseTranscript(transcript, transcript.source_sha256),
      ),
    ).toThrow();
  });
  it("rejects forged quota, paid upload policy and mismatched progress", () => {
    expect(parseAllowance(allowance).available_seconds).toBe(6000);
    expect(parsePolicy(policy).maximum_file_bytes).toBe(128 * 1024 ** 2);
    expect(parseEntry(entry).site_key).toBe(entry.site_key);
    expect(() =>
      parseAllowance({ ...allowance, available_seconds: 5999 }),
    ).toThrow();
    expect(() => parsePolicy({ ...policy, max_cost_paise: 1 })).toThrow();
    expect(() =>
      parseProgress(
        { ...progress, source_sha256: "a".repeat(64) },
        parseSubmission(progress),
      ),
    ).toThrow();
  });
  it("remembers only a UUID and rejects injected paths", () => {
    rememberSubmission(submissionId);
    expect(localStorage.length).toBe(1);
    expect(savedSubmissionId()).toBe(submissionId);
    localStorage.setItem(
      "ac.xray.submission.v1",
      "https://other.example/private",
    );
    expect(savedSubmissionId()).toBeNull();
  });
});
