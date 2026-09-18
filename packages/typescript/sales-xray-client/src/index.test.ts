import { describe, expect, it } from "vitest";
import {
  assertCheckpointRevision,
  createMeasurementProposal,
  createEntryUrl,
  createReviewProposal,
  parseSegments,
  validateCheckpoint,
} from "./index";

const sha = "a".repeat(64);
const features = "b".repeat(64);
const c1 = () => ({
  schema: "ac.sales-xray.signal-checkpoint/1",
  stage: "C1",
  source_sha256: sha,
  feature_sha256: features,
  source_rate: 48000,
  source_channels: 2,
  source_codec: "mp3",
  acoustics: {
    format: "ac.audioatlas.features/1",
    rate: 16000,
    channels: 2,
    sample_count: 16000,
    rows: 200,
    window_samples: 640,
    hop_samples: 160,
    source_sha256: sha,
    feature_sha256: features,
  },
  timebase: {
    clock: "decoded_audio_track",
    rate: 16000,
    source_track_start_seconds: 0.025,
    source_track_time_base: "1/14112000",
    source_mapping_status: "uncertified_codec_delay_origin_and_discontinuities",
    container_video_sync_certified: false,
  },
  display: {
    channels: [
      {
        channel: 0,
        time_s: [0, 0.1, 0.2],
        dbfs: [-20, null, -18],
        f0_hz: [null, 200, 210],
        display_stride: 10,
      },
    ],
  },
});
const segment = {
  id: "s1",
  speaker_id: "speaker-a",
  start_ms: 0,
  end_ms: 900,
  text: "नमस्ते <script>alert('x')</script>",
};
const checkpoint = () => ({
  schema_version: "sales-xray-checkpoint.v1",
  run_id: "run-local",
  revision: "revision-1",
  source: { sha256: sha, duration_ms: 1000, provenance: "Synthetic source." },
  transcript: {
    revision: "script-v1",
    provenance: "Known script; not ASR.",
    segments: [segment],
  },
  channels: [
    {
      label: "Level",
      unit: "dBFS",
      clock: "decoded_audio_track",
      window_ms: 40,
      hop_ms: 10,
      points: [
        { start_ms: 0, value: -20 },
        { start_ms: 10, value: null },
      ],
    },
  ],
});
describe("checkpoint imports", () => {
  it("rejects conflicting local contents under the same immutable revision", () => {
    const first = validateCheckpoint(checkpoint());
    const second = validateCheckpoint(checkpoint());
    second.transcript.segments[0]!.text =
      "A conflicting transcript under the same revision.";
    expect(() => assertCheckpointRevision([first], second)).toThrow(
      /new immutable revision/,
    );
    second.revision = "revision-2";
    expect(() => assertCheckpointRevision([first], second)).not.toThrow();
    expect(() =>
      assertCheckpointRevision([first], validateCheckpoint(checkpoint())),
    ).not.toThrow();
  });
  it("reads native C1 without inventing a transcript and preserves clock discrepancy and nulls", () => {
    const parsed = validateCheckpoint(c1());
    expect(parsed.transcript.segments).toEqual([]);
    expect(parsed.channels[0]).toMatchObject({
      window_ms: 40,
      hop_ms: 10,
      display_stride: 10,
      clock: "decoded_audio_track",
      points: [
        { start_ms: 0, value: -20 },
        { start_ms: 100, value: null },
        { start_ms: 200, value: -18 },
      ],
    });
    expect(parsed.signal_metadata).toMatchObject({
      source_track_start_seconds: 0.025,
      container_video_sync_certified: false,
      source_rate: 48000,
      decoded_rate: 16000,
    });
    expect(parsed.source.sha256).toBe(sha);
  });
  it("rejects a mismatched feature/source binding", () => {
    const v = c1();
    v.acoustics.source_sha256 = features;
    expect(() => validateCheckpoint(v)).toThrow(/incompatible/);
  });
  it("rejects unsorted or out-of-clock points", () => {
    const v = c1();
    v.display.channels[0]!.time_s = [0.2, 0.1, 0];
    expect(() => validateCheckpoint(v)).toThrow(/ordered/);
  });
  it("rejects incompatible native timebase", () => {
    const v = c1();
    v.timebase.rate = 48000;
    expect(() => validateCheckpoint(v)).toThrow(/incompatible/);
  });
  it("rejects truncated channel arrays", () => {
    const v = c1();
    v.display.channels[0]!.dbfs.pop();
    expect(() => validateCheckpoint(v)).toThrow(/invalid/);
  });
  it("keeps Unicode and HTML-looking transcript text as literal data", () => {
    expect(validateCheckpoint(checkpoint()).transcript.segments[0]?.text).toBe(
      segment.text,
    );
  });
  it("rejects duplicate evidence IDs", () => {
    expect(() => parseSegments([segment, segment], 1000)).toThrow(/identity/);
  });
  it("rejects evidence exceeding the source clock", () => {
    expect(() => parseSegments([{ ...segment, end_ms: 1001 }], 1000)).toThrow(
      /timing/,
    );
  });
  it("rejects nonfinite measurements", () => {
    const v = checkpoint();
    v.channels[0]!.points[0]!.value = Infinity;
    expect(() => validateCheckpoint(v)).toThrow(/finite/);
  });
});
describe("presentation entry adapters", () => {
  it.each(["standalone", "lms", "free-course", "website"] as const)(
    "preserves the same run for %s without tenant or identity parameters",
    (presentation) => {
      const url = new URL(
        createEntryUrl({
          origin: "https://xray.example.test",
          allowedOrigins: ["https://xray.example.test"],
          presentation,
          runId: "run_123",
        }),
      );
      expect([...url.searchParams.entries()]).toEqual([
        ["presentation", presentation],
        ["run", "run_123"],
      ]);
    },
  );
  it.each([
    "https://evil.test",
    "https://xray.example.test.evil.test",
    "https://user:password@xray.example.test",
    "https://xray.example.test/other",
    "javascript:alert(1)",
  ])("rejects an unapproved destination: %s", (origin) => {
    expect(() =>
      createEntryUrl({
        origin,
        allowedOrigins: ["https://xray.example.test"],
        presentation: "lms",
      }),
    ).toThrow();
  });
  it("rejects IDs that could be interpreted as URLs", () => {
    expect(() =>
      createEntryUrl({
        origin: "https://xray.example.test",
        allowedOrigins: ["https://xray.example.test"],
        presentation: "website",
        runId: "../../other?tenant=other",
      }),
    ).toThrow();
  });
});
describe("local review proposals", () => {
  it("binds a C1 technical correction to exact channel, point, profile and feature revision without inventing transcript text", () => {
    const source = validateCheckpoint(c1());
    const proposal = createMeasurementProposal(
      source,
      0,
      1,
      "Reproduce this unavailable level window.",
      true,
    );
    expect(proposal.anchor).toMatchObject({
      physical_channel_index: 0,
      measurement: "dbfs",
      time_ms: 100,
      value: null,
      unit: "dBFS",
      clock: "decoded_audio_track",
      window_ms: 40,
      hop_ms: 10,
      display_stride: 10,
      measurement_revision: features,
    });
    expect(proposal.source_evidence).toMatchObject({
      source_sha256: sha,
      feature_sha256: features,
      audio_sha256_matched: true,
      feature_binary_verified: false,
      checkpoint_authorship_verified: false,
    });
    expect(proposal).toMatchObject({
      reviewer_identity: null,
      submitted: false,
      transcript_revision: null,
      segment_id: null,
      lane: "measurements",
      numeric_publication: "withheld",
    });
  });
  it("rejects a missing or out-of-range measurement selection", () => {
    const source = validateCheckpoint(c1());
    expect(() =>
      createMeasurementProposal(source, 0, 9000, "A correction", false),
    ).toThrow(/exact measurement/);
    expect(() =>
      createMeasurementProposal(source, -1, 0, "A correction", false),
    ).toThrow(/exact measurement/);
  });
  it("binds immutable revisions without impersonating either reviewer or claiming submission", () => {
    expect(
      createReviewProposal(
        { run_id: "run_1", revision: "c1-v3", transcript_revision: "c2-v2" },
        "measurements",
        "s1",
        " Recheck speaker attribution. ",
      ),
    ).toMatchObject({
      revision: "c1-v3",
      transcript_revision: "c2-v2",
      lane: "measurements",
      proposed_correction: "Recheck speaker attribution.",
      reviewer_identity: null,
      submitted: false,
      state: "local_unsubmitted_proposal",
    });
  });
  it("requires source evidence and a nonempty proposal", () => {
    expect(() =>
      createReviewProposal(
        { run_id: "run_1", revision: "r1", transcript_revision: "t1" },
        "contextual",
        "s1",
        " ",
      ),
    ).toThrow();
  });
});
