import { describe, expect, it } from "vitest";

import {
  clock,
  normalizeBundle,
  normalizeCall,
  normalizeQueue,
  pickRun,
  segmentAt,
  speakerNames,
  when,
} from "./call-data";
import { filterQuery, queueApiPath, queueFilters } from "./queue-query";
import { startAt, wordDiff } from "./review-logic";
import { reportPillars, REPORT_PILLARS } from "./report-pillars";
import {
  compareReports,
  keyAction,
  nextSpeed,
  waveformBars,
} from "./review-logic";

const quote = (segment: string, start = 1000) => ({
  segment_id: segment,
  quote: "हमें budget देखना होगा",
  start_ms: start,
  end_ms: start + 2000,
});
const finding = (title: string, segment = "s1") => ({
  title,
  explanation: `${title} explained`,
  evidence: [quote(segment)],
});
const rawReport = (overrides: Record<string, unknown> = {}) => ({
  summary: "The rep opened warmly.",
  summary_evidence: [quote("s1")],
  verdict: "A follow-up was agreed.",
  strengths: [finding("Warm opening")],
  improvements: [finding("Price came too early", "s2")],
  missed_opportunities: [],
  objection_analysis: [],
  closing_analysis: [],
  dimensions: [
    {
      dimension_id: "qualification",
      label: "Qualification",
      status: "observed",
      call_state: "needs_attention",
      observation: "Budget was not confirmed.",
      evidence: [quote("s2")],
    },
  ],
  report_sections: [],
  call_map: {
    speakers: [
      { speaker_id: "A", role: "seller" },
      { speaker_id: "B", role: "prospect" },
    ],
  },
  overview: {
    diagnosis: { text: "Price before value", evidence: [quote("s2")] },
    outcome: {
      kind: "follow_up",
      text: "Prospect asked for a demo",
      evidence: [quote("s3")],
    },
    strength_details: [
      { finding_index: 0, why_it_matters: "Trust built early" },
    ],
    improvement_details: [
      {
        finding_index: 0,
        what_happened: {
          text: "Quoted the fee in minute two",
          evidence: [quote("s2")],
        },
        why_it_matters: "Anchored on cost",
        replacement_behavior: "Ask about impact before price",
      },
    ],
    golden_moments: [],
    rewatch: [],
    conversation_change: null,
    next_call_focus: {
      improvement_index: 0,
      behavior: "Delay price",
      target: "After two impact questions",
    },
    practice: {
      improvement_index: 0,
      instructions: "Role-play the opening",
      success_condition: "Two questions first",
    },
    final_assessment: {
      repeat: "Warmth",
      fix_first: "Price timing",
      next_focus: "Impact",
      assessment: "Promising",
    },
  },
  ...overrides,
});

describe("call review data", () => {
  it("normalizes the queue with defaults for anything missing", () => {
    const queue = normalizeQueue({
      items: [
        {
          recording_id: "r1",
          status: "weird",
          rep: null,
          organisation: { id: "o1" },
        },
      ],
      counts: { ready: 2 },
      window: { truncated: true },
    });
    expect(queue.items[0]).toMatchObject({
      recordingId: "r1",
      status: "uploaded",
      rep: { label: "Unknown rep", personId: null },
      organisation: { id: "o1", name: "Unknown organisation" },
    });
    expect(queue.counts).toEqual({
      ready: 2,
      analysing: 0,
      failed: 0,
      uploaded: 0,
    });
    expect(queue.truncated).toBe(true);
    expect(normalizeQueue(null).items).toEqual([]);
  });

  it("opens the asked-for run only when it has a report, else the newest reported one", () => {
    const call = normalizeCall({
      runs: [
        { id: "new", state: "failed", report_id: null },
        { id: "mid", state: "completed", report_id: "rep-2" },
        { id: "old", state: "completed", report_id: "rep-1" },
      ],
    });
    expect(pickRun(call, "old")?.id).toBe("old");
    expect(pickRun(call, "new")?.id).toBe("mid");
    expect(pickRun(call, undefined)?.id).toBe("mid");
    expect(pickRun(normalizeCall({ runs: [] }), undefined)).toBeNull();
  });

  it("reads a call's failed steps with defaults, and none when the field is missing", () => {
    expect(normalizeCall({}).failedJobs).toEqual([]);
    const call = normalizeCall({
      failed_jobs: [
        {
          job_id: "job-1",
          stage: "C2",
          recording_id: "rec-1",
          attempts: 3,
          code: "provider_timeout",
          failed_at: "2026-10-11T03:00:00Z",
          retryable: true,
        },
        { job_id: "job-2" },
      ],
    });
    expect(call.failedJobs[0]).toEqual({
      jobId: "job-1",
      stage: "C2",
      recordingId: "rec-1",
      attempts: 3,
      code: "provider_timeout",
      failedAt: "2026-10-11T03:00:00Z",
      retryable: true,
    });
    expect(call.failedJobs[1]).toMatchObject({
      stage: "?",
      code: "not_recorded",
      retryable: false,
    });
  });

  it("builds the bundle, its audio URL and speaker names from the call map", () => {
    const bundle = normalizeBundle({
      run_id: "run-1",
      report: rawReport(),
      story: null,
      transcript: {
        revision: "t1",
        segments: [
          {
            id: "s1",
            speaker_id: "A",
            start_ms: 0,
            end_ms: 2000,
            text: "Namaste",
          },
          {
            id: "s2",
            speaker_id: "B",
            start_ms: 2000,
            end_ms: 5000,
            text: "कितने का पड़ेगा?",
          },
          { id: "", speaker_id: "B", start_ms: 9, end_ms: 9, text: "dropped" },
        ],
      },
      audio_source_url: "https://evil.example/steal",
    });
    expect(bundle.audioUrl).toBe("/v1/admin/conversation/runs/run-1/source");
    expect(bundle.transcript.segments).toHaveLength(2);
    expect(speakerNames(bundle.report, bundle.transcript.segments)).toEqual({
      A: "Rep",
      B: "Prospect",
    });
    expect(
      speakerNames(
        { ...bundle.report, speakers: {} },
        bundle.transcript.segments,
      ),
    ).toEqual({
      A: "Speaker 1",
      B: "Speaker 2",
    });
    expect(bundle.report.overview?.practiceDrill?.instructions).toBe(
      "Role-play the opening",
    );
    expect(bundle.waveform).toBeNull();
  });

  it("finds the line being heard and formats time", () => {
    const segments = [0, 2000, 5000].map((startMs, index) => ({
      id: `s${index}`,
      speakerId: null,
      startMs,
      endMs: startMs + 1000,
      text: "",
    }));
    expect(segmentAt(segments, 0)).toBe(0);
    expect(segmentAt(segments, 4999)).toBe(1);
    expect(segmentAt(segments, 99999)).toBe(2);
    expect(segmentAt([], 10)).toBe(-1);
    expect(clock(65_000)).toBe("1:05");
    expect(clock(3_725_000)).toBe("1:02:05");
    expect(clock(null)).toBe("–:––");
    expect(when("2026-10-10T06:30:00Z")).toContain("12:00");
    expect(when("not a date")).toBe("Unknown time");
  });
});

describe("six pillars", () => {
  it("presents the report in the spec's order and keeps gaps as gaps", () => {
    const report = normalizeBundle({ report: rawReport(), story: null }).report;
    const pillars = reportPillars(report, 60_000);
    expect(pillars.map((pillar) => pillar.label)).toEqual(
      REPORT_PILLARS.map((pillar) => pillar.label),
    );
    const picture = pillars[0]!.entries;
    expect(picture[0]).toMatchObject({ label: "Call outcome", gap: true });
    expect(
      picture.find((entry) => entry.label === "Possible influence"),
    ).toMatchObject({ hypothesis: true });
    const skills = pillars[4]!.entries;
    expect(skills).toHaveLength(8);
    expect(
      skills.find((entry) => entry.label.startsWith("Qualification"))?.label,
    ).toBe("Qualification · Needs Attention");
    expect(skills.filter((entry) => entry.gap)).toHaveLength(7);
  });

  it("reads outcome and timeline from the story projection", () => {
    const report = normalizeBundle({
      report: rawReport(),
      story: {
        phases: [
          { name: "opening", start_ms: 0 },
          { name: "pitch", start_ms: 30_000 },
        ],
        outcome: {
          kind: "won",
          next_step_rung: "none",
          next_step_when: null,
          evidence: [quote("s9")],
        },
        next_step: null,
        prospect_tasks: [],
        prospect_commitments: [],
        seller_commitments: [],
      },
    }).report;
    const pillars = reportPillars(report, 60_000);
    expect(pillars[0]!.entries[0]).toMatchObject({
      label: "Call outcome",
      text: "Won",
    });
    expect(pillars[1]!.timeline).toEqual([
      { label: "Opening", startMs: 0, endMs: 30_000 },
      { label: "Offer discussion", startMs: 30_000, endMs: 60_000 },
    ]);
  });
});

describe("review screen logic", () => {
  it("maps keys to actions and ignores modified keys", () => {
    expect(keyAction({ key: " " })).toEqual({ kind: "toggle" });
    expect(keyAction({ key: "ArrowLeft" })).toEqual({
      kind: "seek",
      byMs: -5000,
    });
    expect(keyAction({ key: "ArrowRight", shiftKey: true })).toEqual({
      kind: "seek",
      byMs: 15000,
    });
    expect(keyAction({ key: "s" })).toEqual({ kind: "tab", tab: "pillars" });
    expect(keyAction({ key: "n" })).toEqual({ kind: "call", step: 1 });
    expect(keyAction({ key: "k", ctrlKey: true })).toBeNull();
    expect(keyAction({ key: "x" })).toBeNull();
  });

  it("steps speed within bounds", () => {
    expect(nextSpeed(1, 1)).toBe(1.25);
    expect(nextSpeed(2, 1)).toBe(2);
    expect(nextSpeed(0.75, -1)).toBe(0.75);
  });

  it("draws waveform bars from the loudest point per slice, honestly empty without data", () => {
    const waveform = {
      durationMs: 4000,
      points: [0, 1000, 2000, 3000].map((startMs, index) => ({
        startMs,
        level: [0.1, 0.4, null, 0.2][index]!,
      })),
    };
    expect(waveformBars(waveform, 2)).toEqual([1, 0.5]);
    expect(waveformBars(null, 10)).toEqual([]);
    expect(
      waveformBars({ durationMs: 1, points: [{ startMs: 0, level: 0 }] }, 3),
    ).toEqual([0, 0, 0]);
  });

  it("compares two runs field by field", () => {
    const left = normalizeBundle({ report: rawReport() }).report;
    const right = normalizeBundle({
      report: rawReport({
        verdict: "No next step.",
        strengths: [finding("Clear agenda")],
      }),
    }).report;
    const rows = compareReports(left, right);
    expect(rows.find((row) => row.label === "Summary")?.same).toBe(true);
    expect(rows.find((row) => row.label === "Verdict")).toMatchObject({
      same: false,
      right: "No next step.",
    });
    expect(rows.find((row) => row.label === "Strengths")?.same).toBe(false);
    expect(rows.find((row) => row.label === "Qualification")?.left).toBe(
      "Needs Attention",
    );
  });
});

describe("queue address", () => {
  it("keeps valid filters and drops anything malformed", () => {
    const filters = queueFilters({
      status: "ready",
      organisation: "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
      rep: "not-a-uuid",
      language: "mr-Deva+en",
      provider: "gemini<script>",
      since: "2026-10-01",
      until: "2026-13-45",
      cursor: ["bzo1MA", "other"],
    });
    expect(filters).toEqual({
      status: "ready",
      organisation: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      language: "mr-Deva+en",
      since: "2026-10-01",
      cursor: "bzo1MA",
    });
    expect(filterQuery(filters, ["cursor"])).toBe(
      "status=ready&organisation=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa&language=mr-Deva%2Ben&since=2026-10-01",
    );
    expect(queueApiPath({}, 20)).toBe("/v1/admin/conversation/calls?limit=20");
  });

  it("filters by prompt version, from the address and the facet", () => {
    expect(queueFilters({ prompt: "coaching-v5" })).toEqual({
      prompt: "coaching-v5",
    });
    expect(queueFilters({ prompt: "v5 <b>" })).toEqual({});
    expect(queueApiPath({ prompt: "coaching-v5", status: "ready" }, 50)).toBe(
      "/v1/admin/conversation/calls?status=ready&prompt=coaching-v5&limit=50",
    );
    expect(
      normalizeQueue({
        facets: { prompts: [{ value: "coaching-v5", count: 3 }] },
      }).facets.prompts,
    ).toEqual([{ value: "coaching-v5", label: "coaching-v5", count: 3 }]);
    expect(normalizeQueue({}).facets.prompts).toEqual([]);
  });
});

describe("shared moment", () => {
  it("accepts a whole number of ms within a day, and nothing else", () => {
    expect(startAt("83000")).toBe(83_000);
    expect(startAt("0")).toBe(0);
    expect(startAt(undefined)).toBeNull();
    expect(startAt("-5")).toBeNull();
    expect(startAt("1.5")).toBeNull();
    expect(startAt("99999999")).toBeNull();
    expect(startAt("12abc")).toBeNull();
  });
});

describe("compared runs", () => {
  it("marks the words each side has that the other lacks, Devanagari too", () => {
    const diff = wordDiff(
      "Buyer has not committed to a meeting",
      "Buyer has committed to a dated meeting",
    )!;
    expect(diff.left).toEqual([
      { text: "Buyer has ", changed: false },
      { text: "not ", changed: true },
      { text: "committed to a meeting", changed: false },
    ]);
    expect(diff.right.filter((part) => part.changed)).toEqual([
      { text: "dated ", changed: true },
    ]);
    const hindi = wordDiff("कितने का पड़ेगा?", "कितने का होगा?")!;
    expect(hindi.left.filter((part) => part.changed)[0]!.text).toBe("पड़ेगा?");
    // The words always add back up to the original text.
    expect(diff.right.map((part) => part.text).join("")).toBe(
      "Buyer has committed to a dated meeting",
    );
  });

  it("gives up on very long texts instead of slowing the screen", () => {
    expect(wordDiff("a b c", "a b d", 10)).toBeNull();
    expect(wordDiff("", "")).toEqual({ left: [], right: [] });
  });
});
