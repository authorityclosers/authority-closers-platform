import { expect, it } from "vitest";

import type { Transcript } from "../report-contract";
import { readStructure } from "./structure";

const transcript = {
  source_sha256: "a".repeat(64),
  revision: "r1",
  timebase_id: "t1",
  duration_ms: 43_570,
  segments: [
    {
      id: "s1",
      speaker_id: "speaker_0",
      start_ms: 0,
      end_ms: 5_200,
      text: "Hello, is now a good time?",
    },
    {
      id: "s2",
      speaker_id: "speaker_1",
      start_ms: 5_400,
      end_ms: 10_300,
      text: "Yes. Owners and next steps are often missed.",
    },
  ],
} as Transcript;

const evidence = (id: string, start: number, end: number, quote: string) => ({
  segment_id: id,
  quote,
  start_ms: start,
  end_ms: end,
});

function structure(pointer: Record<string, unknown> = {}) {
  return {
    version: "report-structure/1",
    overview: {
      summary: "A sample review was agreed.",
      evidence: [
        evidence(
          "s2",
          5_400,
          10_300,
          "Owners and next steps are often missed.",
        ),
      ],
      score: null,
      score_status: "not_scored",
      biggest_strength: {
        text: "You checked the timing.",
        evidence: [evidence("s1", 0, 5_200, "Hello, is now a good time?")],
        source: "pillars.strongest_part",
      },
      biggest_improvement: null,
      call_statistics: {
        status: "available",
        duration_ms: 43_570,
        talk_share_percent: { rep: 56.0, prospect: 44.0 },
        questions_asked: { rep: 2, prospect: 1 },
        longest_rep_turn: {
          speaker_id: "speaker_0",
          start_ms: 20_200,
          end_ms: 26_000,
          duration_ms: 5_800,
        },
        speakers: [
          { speaker_id: "speaker_0", role: "rep" },
          { speaker_id: "speaker_1", role: "prospect" },
        ],
      },
    },
    pointers: Array.from({ length: 27 }, (_, index) => ({
      number: index + 1,
      status: "insufficient_evidence",
      score: null,
      score_status: "not_scored",
      observations: [],
      related_dimensions: [],
      ...(index === 0 ? pointer : {}),
    })),
  };
}

it("reads measured call numbers and the analysis' own highlights", () => {
  const view = readStructure(structure(), transcript, null, null)!;
  expect(view.overview.stats).toEqual({
    duration: { value: "00:44", sub: "44 sec" },
    talk: { value: "56 : 44", sub: "Salesperson : Prospect" },
    questions: { value: "2 : 1", sub: "Salesperson : Prospect" },
    longest: { value: "00:06", sub: "6 sec" },
  });
  expect(view.overview.strength?.text).toBe("You checked the timing.");
  expect(view.overview.improvement).toBeUndefined();
  expect(view.overview.score).toBeUndefined();
  expect(view.aiDraft).toBe(false);
});

it("shows an unassessed pointer as not scored, never as a judgement about the call", () => {
  const view = readStructure(
    structure({
      observations: [
        {
          text: "You asked about owners.",
          evidence: [
            evidence(
              "s2",
              5_400,
              10_300,
              "Owners and next steps are often missed.",
            ),
          ],
        },
      ],
    }),
    transcript,
    null,
    null,
  )!;
  const first = view.pointers![0];
  expect(view.pointers).toHaveLength(27);
  expect(first.name).toBe("Call Opening & First Impression");
  expect(first.status).toBeNull();
  expect(first.score).toBeNull();
  expect(first.whatHappened).toBe("You asked about owners.");
  expect(first.evidence[0]).toMatchObject({ who: "prospect", at_ms: 5_400 });
});

it("keeps an analysis score as an AI draft and drops evidence that is not in the transcript", () => {
  const view = readStructure(
    {
      ...structure({
        status: "good",
        score: 82,
        score_status: "ai_draft",
        what_happened: "You opened clearly.",
        how_to_improve: ["Say what the prospect gets from the call."],
        evidence: [
          evidence("s1", 0, 5_200, "Hello, is now a good time?"),
          evidence("missing", 0, 10, "Not in this call"),
        ],
      }),
      overview: {
        ...structure().overview,
        score: 78,
        score_label: "Good",
        score_line: "Handled well.",
      },
    },
    transcript,
    null,
    null,
  )!;
  const first = view.pointers![0];
  expect(view.aiDraft).toBe(true);
  expect(view.overview.score).toEqual({
    value: 78,
    label: "Good",
    line: "Handled well.",
  });
  expect(first).toMatchObject({
    status: "good",
    score: 82,
    howToImprove: ["Say what the prospect gets from the call."],
  });
  expect(first.evidence).toHaveLength(1);
  expect(first.evidence[0].who).toBe("you");
});

it("ignores anything that is not the known structure version", () => {
  expect(
    readStructure({ version: "other" }, transcript, null, null),
  ).toBeNull();
  expect(readStructure(null, transcript, null, null)).toBeNull();
});
