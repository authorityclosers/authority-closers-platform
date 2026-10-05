import { describe, expect, it } from "vitest";

import { extractInsight } from "./calls-insights";

const evidence = (start_ms: number) => ({
  segment_id: "s1",
  quote: "fictional quote",
  start_ms,
  end_ms: start_ms + 2000,
});

const report = {
  submission_id: "call-1",
  report: {
    content: {
      verdict: "Fictional verdict",
      strengths: [
        {
          title: "Clear discovery",
          explanation: "x",
          evidence: [evidence(5000)],
        },
      ],
      missed_opportunities: [
        { title: "Budget gap", explanation: "y", evidence: [] },
      ],
      next_action: {
        title: "Book the Tuesday review",
        explanation: "z",
        evidence: [evidence(40000)],
      },
      overview: {
        final_assessment: {
          assessment: "Efficient discovery; budget gap bypassed.",
          fix_first: "Acknowledge budget comments directly.",
          next_focus: "Clarify how rigid the budget is.",
          repeat: "Keep the discovery order.",
        },
        rewatch: [
          {
            text: "Objection plus implementation question",
            evidence: [evidence(25000)],
            purpose: "learn",
          },
        ],
        golden_moments: [
          {
            strength_index: 0,
            evidence_index: 0,
            why_effective: "Clean discovery question",
          },
        ],
      },
    },
  },
};

const callRecord = {
  version: "call-record/1",
  numbers: {
    duration_ms: 761000,
    overlaps: 0,
    speakers: [
      {
        speaker_id: "a",
        talk_ms: 1,
        talk_share: 0.6,
        questions: 7,
        longest_monologue_ms: 1,
      },
      {
        speaker_id: "b",
        talk_ms: 1,
        talk_share: 0.4,
        questions: 2,
        longest_monologue_ms: 1,
      },
    ],
  },
  facts: [
    {
      statement: "Will send the brochure tomorrow",
      evidence: [evidence(1000)],
      tag: "Next steps and commitments",
    },
    {
      statement: "Monthly profit is around 10-15k",
      evidence: [evidence(2000)],
      tag: "Business details",
    },
  ],
  tags: null,
  call_type: "first_meeting",
};

describe("extractInsight", () => {
  it("reads the wrapped report content and the call record", () => {
    const insight = extractInsight(callRecord, report);
    expect(insight.assessment).toBe(
      "Efficient discovery; budget gap bypassed.",
    );
    expect(insight.fixFirst).toBe("Acknowledge budget comments directly.");
    expect(insight.nextFocus).toBe("Clarify how rigid the budget is.");
    expect(insight.durationMs).toBe(761000);
    expect(insight.questions).toBe(9);
    expect(insight.callType).toBe("first_meeting");
    expect(insight.signals).toEqual({
      commitments: 1,
      business: 1,
      concerns: 0,
    });
    expect(insight.strengths).toBe(1);
    expect(insight.missed).toBe(1);
    expect(insight.moments.map((moment) => moment.startMs)).toEqual([
      25000, 5000, 40000,
    ]);
  });

  it("degrades to empty insights instead of failing on missing data", () => {
    const insight = extractInsight(null, {
      report: { content: { verdict: "Only a verdict" } },
    });
    expect(insight.assessment).toBe("Only a verdict");
    expect(insight.durationMs).toBeNull();
    expect(insight.questions).toBeNull();
    expect(insight.strengths).toBeNull();
    expect(insight.missed).toBeNull();
    expect(insight.signals).toEqual({
      commitments: null,
      business: null,
      concerns: null,
    });
    expect(insight.moments).toEqual([]);
    expect(extractInsight("nonsense", 42).assessment).toBeNull();
  });

  it("counts only approved categories with record evidence", () => {
    const facts = [
      {
        statement: "A commitment",
        tag: "Next steps and commitments",
        evidence: [],
      },
      { statement: "A promise", tag: "promise", evidence: [evidence(1)] },
      { statement: "next step money ₹", evidence: [evidence(2)] },
      { statement: "A concern", tag: "Concerns", evidence: [evidence(3)] },
      ...callRecord.facts,
    ];
    expect(extractInsight({ ...callRecord, facts }, report).signals).toEqual({
      commitments: 1,
      business: 1,
      concerns: 1,
    });
  });

  it.each([undefined, -1, NaN, Infinity])(
    "keeps invalid or missing question counts unavailable (%s)",
    (questions) => {
      const record = {
        ...callRecord,
        numbers: {
          ...callRecord.numbers,
          speakers: [{ ...callRecord.numbers.speakers[0], questions }],
        },
      };
      const insight = extractInsight(record, report);
      expect(insight.questions).toBeNull();
      expect(insight.speakers).toEqual([]);
      expect(insight.assessment).toBeTruthy();
    },
  );

  it("rejects blank evidence rather than counting it", () => {
    const record = {
      ...callRecord,
      facts: [
        { ...callRecord.facts[0], evidence: [{ ...evidence(1), quote: " " }] },
      ],
    };
    expect(extractInsight(record, report).signals.commitments).toBeNull();
  });
});
