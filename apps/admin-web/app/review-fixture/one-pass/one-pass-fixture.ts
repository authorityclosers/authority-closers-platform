/** Fictional answers for the one-pass trial screens (no API, no call, no person). */

const side = (
  pipeline: string,
  inr: number,
  ms: number,
  facts: string[][],
) => ({
  pipeline,
  available: true,
  state: "succeeded",
  reason: null,
  audio_ms: 840_000,
  cost_inr: inr,
  per_minute_inr: inr / 14,
  flex_cost_inr: pipeline === "one_pass" ? inr / 2 : null,
  standard_cost_inr: pipeline === "one_pass" ? inr : null,
  duration_ms: ms,
  tokens_in: pipeline === "one_pass" ? 46_000 : 61_000,
  tokens_out: pipeline === "one_pass" ? 18_000 : 26_000,
  stages:
    pipeline === "one_pass"
      ? [
          {
            key: "transcription",
            label: "Transcription (Gemini 3.1 Flash-Lite)",
            inr: 1.96,
            tokens_in: 27_000,
            tokens_out: 7_400,
            ms: 41_000,
            model: "gemini-3.1-flash-lite",
            tier: "standard",
          },
          {
            key: "analysis",
            label: "One pass (Gemini 3.8 Flash)",
            inr: 3.9,
            tokens_in: 19_000,
            tokens_out: 10_600,
            ms: 74_000,
            model: "gemini-3.8-flash",
            tier: "standard",
          },
        ]
      : [
          {
            key: "transcription",
            label: "Transcription (Scribe)",
            inr: 5.13,
            ms: 52_000,
            model: "scribe_v2",
          },
          {
            key: "facts",
            label: "C4 facts",
            inr: 1.1,
            tokens_in: 16_000,
            tokens_out: 1_900,
            ms: 31_000,
            model: "gemini-3.8-flash",
          },
          {
            key: "coaching",
            label: "C5 report and coaching",
            inr: 2.6,
            tokens_in: 10_200,
            tokens_out: 4_600,
            ms: 66_000,
            model: "gemini-3.8-flash",
          },
          {
            key: "pointer_review",
            label: "Pointer review",
            inr: 2.6,
            tokens_in: 6_700,
            tokens_out: 5_600,
            ms: 58_000,
            model: "gemini-3.8-flash",
          },
          {
            key: "fast",
            label: "Call data: fast",
            inr: 1.5,
            tokens_in: 6_200,
            tokens_out: 2_700,
            ms: 22_000,
            model: "gemini-3.8-flash",
          },
          {
            key: "deep",
            label: "Call data: deep",
            inr: 3.5,
            tokens_in: 22_000,
            tokens_out: 11_000,
            ms: 95_000,
            model: "gemini-3.8-flash",
          },
        ],
  transcript: {
    source:
      pipeline === "one_pass" ? "Gemini 3.1 Flash-Lite" : "ElevenLabs Scribe",
    segments: 42,
    speakers: 2,
    words: pipeline === "one_pass" ? 1_980 : 2_040,
    rows: [],
  },
  objects: facts.map(([type, label, display]) => ({
    type,
    label,
    display,
    confidence: 0.9,
  })),
  c4_observations: pipeline === "one_pass" ? 38 : 31,
  pointers: {
    overall: pipeline === "one_pass" ? 68 : 71,
    line: "A clear opening; the price came before the need.",
    rows: [
      {
        id: "call_opening_first_impression",
        label: "Call opening",
        status: "good",
        score: 78,
      },
      {
        id: "needs_challenges",
        label: "Needs and challenges",
        status: pipeline === "one_pass" ? "average" : "good",
        score: pipeline === "one_pass" ? 62 : 72,
      },
      {
        id: "discussing_pricing",
        label: "Discussing pricing",
        status: "needs_improvement",
        score: 45,
      },
    ],
  },
  coaching: {
    summary:
      "A first call with a solar buyer; the price came before the roof size was known.",
    verdict: "Book the site visit the buyer asked for.",
    strengths: ["Clear introduction"],
    improvements: ["Ask the roof size before the price"],
    missed_opportunities: ["The buyer mentioned a monthly bill"],
    objections: [],
    closing: [],
    dimensions: [
      { id: "human_connection_trust", status: "observed" },
      {
        id: "qualification",
        status: pipeline === "one_pass" ? "insufficient_evidence" : "observed",
      },
    ],
  },
  checks:
    pipeline === "one_pass"
      ? {
          c2: "ok",
          c4: "ok",
          c5: "ok",
          pointer_review: "ok",
          call_objects: "ok",
          prospect_facts: "ok",
        }
      : null,
  judge: {
    fact_recall: pipeline === "one_pass" ? 0.81 : 0.71,
    truth_coverage: pipeline === "one_pass" ? 0.79 : 0.72,
  },
});

const classic = side("classic", 16.43, 302_000, [
  ["person.name", "Name", "Ravi Patil"],
  ["money.budget", "Budget", "₹2–3 lakh"],
]);
const onePass = side("one_pass", 5.86, 115_000, [
  ["person.name", "Name", "Ravi Patil"],
  ["company.location", "Location", "Pune"],
]);

const summary = {
  calls: 16,
  audio_minutes: 264.3,
  classic: {
    cost_inr: 314.6,
    per_minute_inr: 1.19,
    median_ms: 298_000,
    fact_recall: 0.706,
    truth_coverage: 0.72,
  },
  one_pass: {
    cost_inr: 103.2,
    per_minute_inr: 0.39,
    standard_per_minute_inr: 0.39,
    flex_per_minute_inr: 0.2,
    median_ms: 118_000,
    contracts_passed: 94,
    contracts_checked: 96,
    fact_recall: 0.807,
    truth_coverage: 0.788,
  },
  agreement: {
    fact_overlap: 0.58,
    pointer_status: 0.63,
    pointer_score_gap: 9.4,
    dimension_status: 0.71,
    transcript_vocabulary: 0.66,
  },
};

export const fixturePipeline = {
  environment: "development",
  revision: 2,
  config: {
    mode: "both",
    transcription_tier: "standard",
    analysis_tier: "standard",
    max_call_minutes: 60,
  },
  models: {
    transcription: "gemini-3.1-flash-lite",
    analysis: "gemini-3.8-flash",
  },
  modes: [
    { value: "classic", label: "Today's pipeline", why_not: null },
    {
      value: "both",
      label: "Both, side by side (people see today's)",
      why_not: null,
    },
    {
      value: "one_pass",
      label: "One pass (people see it)",
      why_not:
        "Showing one-pass results to people comes after the side-by-side comparison.",
    },
  ],
  tiers: [
    { value: "standard", label: "Standard (answer in seconds)" },
    { value: "flex", label: "Flex (half price, may wait minutes)" },
  ],
  history: [],
  recent: [
    {
      subject: "fx-01",
      source: "bench",
      state: "succeeded",
      cost_inr: 1.4,
      duration_ms: 61_000,
      audio_ms: 198_900,
      contracts_ok: 6,
      at: "2026-10-21T08:00:00+00:00",
    },
  ],
};

export const fixtureList = {
  environment: "development",
  summary: { calls: { ...summary, calls: 0 }, bench: summary },
  items: [
    {
      subject: { kind: "bench", call: "fx-01" },
      audio_ms: 198_900,
      classic: { state: "succeeded", cost_inr: 4.1, duration_ms: 115_600 },
      one_pass: {
        state: "succeeded",
        cost_inr: 1.4,
        flex_cost_inr: 0.7,
        duration_ms: 61_000,
        contracts_ok: 6,
        at: "2026-10-21T08:00:00+00:00",
      },
      fact_overlap: 0.61,
      pointer_agreement: 0.67,
      dimension_agreement: 0.75,
    },
  ],
};

export const fixtureCompared = {
  environment: "development",
  subject: { kind: "bench", call: "fx-01" },
  classic,
  one_pass: onePass,
  differences: {
    cost_saving_inr: 10.57,
    cost_ratio: 0.36,
    time_ratio: 0.38,
    facts: {
      both: [
        {
          type: "person.name",
          label: "Name",
          classic: "Ravi Patil",
          one_pass: "Ravi Patil",
        },
      ],
      only_classic: [
        {
          type: "money.budget",
          label: "Budget",
          display: "₹2–3 lakh",
          confidence: 0.9,
        },
      ],
      only_one_pass: [
        {
          type: "company.location",
          label: "Location",
          display: "Pune",
          confidence: 0.9,
        },
      ],
      overlap: 0.33,
    },
    pointers: {
      rows: [
        {
          id: "call_opening_first_impression",
          label: "Call opening",
          classic: { status: "good", score: 78 },
          one_pass: { status: "good", score: 78 },
          same_status: true,
        },
        {
          id: "needs_challenges",
          label: "Needs and challenges",
          classic: { status: "good", score: 72 },
          one_pass: { status: "average", score: 62 },
          same_status: false,
        },
      ],
      agreement: 0.5,
      mean_score_gap: 5,
      overall_difference: -3,
    },
    coaching: {
      dimensions: [
        {
          id: "human_connection_trust",
          classic: "observed",
          one_pass: "observed",
        },
        {
          id: "qualification",
          classic: "observed",
          one_pass: "insufficient_evidence",
        },
      ],
      dimension_agreement: 0.5,
    },
    transcript: { word_ratio: 0.97, vocabulary_overlap: 0.66 },
  },
};
