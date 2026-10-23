/**
 * A fictional GET /v1/admin/conversation/engine answer for local review of the analysis
 * engine page. The registry part is registry v0's own description (its fits and
 * projections); the window and module numbers are illustrative, never a measurement.
 */
const REGISTRY = {
  version: "analysis-engine-registry/1",
  digest: "d9c264d3cc",
  planning_fx: 100.0,
  short_call_minutes: 1.0,
  modules: [
    {
      id: "c1.audio-check",
      label: "Audio check",
      stage: "C1",
      models: [],
      status: "live",
      evidence: "Runs on the server; no provider charge.",
      note: "",
      examples: [
        {
          minutes: 2.0,
          rupees: 0.0,
        },
        {
          minutes: 5.0,
          rupees: 0.0,
        },
        {
          minutes: 15.0,
          rupees: 0.0,
        },
      ],
    },
    {
      id: "c2.flash-lite",
      label: "Transcript · Gemini 3.1 Flash-Lite",
      stage: "C2",
      models: ["gemini-3.1-flash-lite"],
      status: "live",
      evidence:
        "16 real calls' receipts, audio and output tokens (one-pass session, 21 Oct)",
      note: "The metrics store prices this step at the price sheet's ₹0.30/min ceiling, so its actual reads about 29% above this fit.",
      examples: [
        {
          minutes: 2.0,
          rupees: 0.466,
        },
        {
          minutes: 5.0,
          rupees: 1.165,
        },
        {
          minutes: 15.0,
          rupees: 3.495,
        },
      ],
    },
    {
      id: "c2.flash-lite.flex",
      label: "Transcript · Flash-Lite on Flex",
      stage: "C2",
      models: ["gemini-3.1-flash-lite:flex"],
      status: "sealed",
      evidence: "the same 16 calls on Flex, fallbacks to standard included",
      note: "The metrics store prices this step at ₹0.15/min.",
      examples: [
        {
          minutes: 2.0,
          rupees: 0.235,
        },
        {
          minutes: 5.0,
          rupees: 0.587,
        },
        {
          minutes: 15.0,
          rupees: 1.762,
        },
      ],
    },
    {
      id: "c4.one-pass-v1",
      label: "One pass · facts, notes and 27-pointer review",
      stage: "C4",
      models: ["gemini-3.8-flash"],
      status: "live",
      evidence:
        "production's exact request on 10 real dev calls (one-pass session, 21-22 Oct)",
      note: "",
      examples: [
        {
          minutes: 2.0,
          rupees: 1.709,
        },
        {
          minutes: 5.0,
          rupees: 1.968,
        },
        {
          minutes: 15.0,
          rupees: 2.834,
        },
      ],
    },
    {
      id: "c4.one-pass-v1.flex",
      label: "One pass on Flex",
      stage: "C4",
      models: ["gemini-3.8-flash:flex"],
      status: "sealed",
      evidence:
        "production's exact request on 10 real dev calls (one-pass session, 21-22 Oct); Flex is half the list price",
      note: "",
      examples: [
        {
          minutes: 2.0,
          rupees: 0.854,
        },
        {
          minutes: 5.0,
          rupees: 0.984,
        },
        {
          minutes: 15.0,
          rupees: 1.417,
        },
      ],
    },
    {
      id: "c4.one-pass-v1.luna-flex",
      label: "One pass · GPT-6 Luna on Flex",
      stage: "C4",
      models: ["gpt-6-luna:flex"],
      status: "trial",
      evidence:
        "13 real calls, production's exact request (one-pass session, 21 Oct)",
      note: "The metrics store has no Luna price yet, so its actual shows as unpriced.",
      examples: [
        {
          minutes: 2.0,
          rupees: 0.198,
        },
        {
          minutes: 5.0,
          rupees: 0.211,
        },
        {
          minutes: 15.0,
          rupees: 0.253,
        },
      ],
    },
    {
      id: "c4.one-pass-v2",
      label: "One pass with Brain 4.0 inside",
      stage: "C4",
      models: ["gemini-3.8-flash"],
      status: "planned",
      evidence:
        "the v1 fit plus the Brain 4.0 part as measured on 8 AC dev calls (22 Oct): +4.5k input, +1.5-2.0k output tokens (midpoint used); every contract passed",
      note: "",
      examples: [
        {
          minutes: 2.0,
          rupees: 2.702,
        },
        {
          minutes: 5.0,
          rupees: 2.962,
        },
        {
          minutes: 15.0,
          rupees: 3.828,
        },
      ],
    },
    {
      id: "c5.after-one-pass",
      label: "Full report · coaching-v5",
      stage: "C5",
      models: ["gemini-3.8-flash"],
      status: "live",
      evidence:
        "production receipts by call length on the 14-day mix, less the one-pass C4 fit",
      note: "",
      examples: [
        {
          minutes: 2.0,
          rupees: 1.23,
        },
        {
          minutes: 5.0,
          rupees: 1.413,
        },
        {
          minutes: 15.0,
          rupees: 2.062,
        },
      ],
    },
    {
      id: "cdf.fast",
      label: "Lead details · fast call data",
      stage: "CDF",
      models: [],
      status: "live",
      evidence:
        "38 real dev calls, 537 min (call data engine, 19 Oct; measured at ₹95/USD)",
      note: "",
      examples: [
        {
          minutes: 2.0,
          rupees: 0.183,
        },
        {
          minutes: 5.0,
          rupees: 0.458,
        },
        {
          minutes: 15.0,
          rupees: 1.374,
        },
      ],
    },
    {
      id: "b4.shadow",
      label: "Brain 4.0 · separate read",
      stage: "B4",
      models: [],
      status: "beta",
      evidence:
        "61 saved production reads on Gemini 3.8 Flash (one-pass session, 22 Oct)",
      note: "Brain 4.0 beta organisations only; the metrics store does not record this read.",
      examples: [
        {
          minutes: 2.0,
          rupees: 0.927,
        },
        {
          minutes: 5.0,
          rupees: 1.04,
        },
        {
          minutes: 15.0,
          rupees: 1.417,
        },
      ],
    },
  ],
  plans: [
    {
      id: "today",
      label: "Today: one pass v1 and the full report, Gemini standard",
      status: "live",
      short: ["c2.flash-lite", "cdf.fast"],
      analysed: ["c2.flash-lite", "c4.one-pass-v1", "c5.after-one-pass"],
      on_demand: [],
      reference: {
        plan: "today",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 203.0,
        per_minute: 0.7138,
      },
      reference_with_uptake: null,
    },
    {
      id: "today-brain4-read",
      label: "Today plus a separate Brain 4.0 read on every analysed call",
      status: "beta",
      short: ["c2.flash-lite", "cdf.fast"],
      analysed: [
        "c2.flash-lite",
        "c4.one-pass-v1",
        "c5.after-one-pass",
        "b4.shadow",
      ],
      on_demand: [],
      reference: {
        plan: "today-brain4-read",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 243.01,
        per_minute: 0.8545,
      },
      reference_with_uptake: null,
    },
    {
      id: "v2",
      label: "Brain 4.0 inside the one-pass read, full report kept",
      status: "planned",
      short: ["c2.flash-lite", "cdf.fast"],
      analysed: ["c2.flash-lite", "c4.one-pass-v2", "c5.after-one-pass"],
      on_demand: [],
      reference: {
        plan: "v2",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 237.78,
        per_minute: 0.8362,
      },
      reference_with_uptake: null,
    },
    {
      id: "v2-report-on-demand",
      label: "v2, full report on demand",
      status: "planned",
      short: ["c2.flash-lite", "cdf.fast"],
      analysed: ["c2.flash-lite", "c4.one-pass-v2"],
      on_demand: ["c5.after-one-pass"],
      reference: {
        plan: "v2-report-on-demand",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 179.47,
        per_minute: 0.6311,
      },
      reference_with_uptake: {
        plan: "v2-report-on-demand",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 185.3,
        per_minute: 0.6516,
      },
    },
    {
      id: "v2-flex-report-on-demand",
      label: "v2 on Flex, full report on demand",
      status: "planned",
      short: ["c2.flash-lite.flex", "cdf.fast"],
      analysed: ["c2.flash-lite.flex", "c4.one-pass-v2.flex"],
      on_demand: ["c5.after-one-pass.flex"],
      reference: {
        plan: "v2-flex-report-on-demand",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 90.65,
        per_minute: 0.3188,
      },
      reference_with_uptake: {
        plan: "v2-flex-report-on-demand",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 93.57,
        per_minute: 0.329,
      },
    },
    {
      id: "v2-luna-flex-report-on-demand",
      label: "v2 on Luna, Flex, full report on demand",
      status: "planned",
      short: ["c2.flash-lite.flex", "cdf.fast"],
      analysed: ["c2.flash-lite.flex", "c4.one-pass-v2.luna-flex"],
      on_demand: ["c5.after-one-pass.flex"],
      reference: {
        plan: "v2-luna-flex-report-on-demand",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 44.79,
        per_minute: 0.1575,
      },
      reference_with_uptake: {
        plan: "v2-luna-flex-report-on-demand",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 47.71,
        per_minute: 0.1678,
      },
    },
    {
      id: "v2-luna-flex-compact",
      label: "As above, with the compact transcript",
      status: "planned",
      short: ["c2.flash-lite-compact.flex", "cdf.fast"],
      analysed: ["c2.flash-lite-compact.flex", "c4.one-pass-v2.luna-flex"],
      on_demand: ["c5.after-one-pass.flex"],
      reference: {
        plan: "v2-luna-flex-compact",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 33.1,
        per_minute: 0.1164,
      },
      reference_with_uptake: {
        plan: "v2-luna-flex-compact",
        calls: 62,
        audio_minutes: 284.4,
        rupees: 36.01,
        per_minute: 0.1266,
      },
    },
  ],
  quality: [
    {
      artifact: "review",
      setup: "Classic pointer review",
      agreement: 0.64,
      low: 0.49,
      high: 0.77,
      evidence:
        "gold v1: the coaching lead's 43 labels on 6 real calls, Flash-Lite transcripts",
      module: "pr.classic",
      nearest: null,
    },
    {
      artifact: "review",
      setup: "One pass v1 review, production's request",
      agreement: null,
      low: null,
      high: null,
      evidence:
        "not scored yet: production's exact requests on the 7 gold calls",
      module: "c4.one-pass-v1",
      nearest: null,
    },
    {
      artifact: "review",
      setup: "Research one pass (onepass2: facts and 27 pointers, Gemini)",
      agreement: 0.72,
      low: 0.57,
      high: 0.83,
      evidence:
        "gold v1: the coaching lead's 43 labels on 6 real calls, Flash-Lite transcripts; a research prompt, not production's request",
      module: null,
      nearest: "c4.one-pass-v1",
    },
    {
      artifact: "review",
      setup: "Luna C review, production's request",
      agreement: null,
      low: null,
      high: null,
      evidence:
        "not scored yet: production's exact requests on the 7 gold calls",
      module: "c4.one-pass-v1.luna-flex",
      nearest: null,
    },
    {
      artifact: "brain4",
      setup: "Brain 4.0, product prompt, Gemini 3.8 Flash (separate read)",
      agreement: 0.55,
      low: 0.38,
      high: 0.7,
      evidence:
        "gold v1: the coaching lead's 43 labels on 6 real calls, Flash-Lite transcripts",
      module: "b4.shadow",
      nearest: null,
    },
    {
      artifact: "brain4",
      setup: "Brain 4.0 inside the one-pass read (v2)",
      agreement: null,
      low: null,
      high: null,
      evidence:
        "not scored yet: production's exact requests on the 7 gold calls; the same Brain 4.0 instructions as the separate read",
      module: "c4.one-pass-v2",
      nearest: null,
    },
    {
      artifact: "brain4",
      setup: "Brain 4.0, product prompt, GPT-6 Luna (separate read)",
      agreement: 0.39,
      low: 0.28,
      high: 0.5,
      evidence:
        "gold v1: the coaching lead's 43 labels on 6 real calls, Flash-Lite transcripts",
      module: null,
      nearest: "c4.one-pass-v2.luna-flex",
    },
    {
      artifact: "brain4",
      setup: "Research Brain 4.0 prompt, Gemini",
      agreement: 0.6,
      low: 0.44,
      high: 0.73,
      evidence:
        "gold v1: the coaching lead's 43 labels on 6 real calls, Flash-Lite transcripts; a research prompt",
      module: null,
      nearest: "b4.shadow",
    },
  ],
  uptake: 0.1,
};

const moduleRow = (
  id: string,
  label: string | null,
  stage: string,
  rows: {
    calls: number;
    steps: number;
    actual: number;
    expected: number | null;
    tokens?: [number, number, number, number];
    model?: string;
    unpriced?: number;
  },
) => {
  const ratio =
    rows.expected && rows.expected > 0
      ? Math.round((rows.actual / rows.expected) * 1000) / 1000
      : null;
  const [inActual, inExpected, outActual, outExpected] = rows.tokens ?? [
    0, 0, 0, 0,
  ];
  return {
    id,
    label,
    stage,
    model: rows.model ?? null,
    modelled: label !== null,
    calls: rows.calls,
    steps: rows.steps,
    unpriced_steps: rows.unpriced ?? 0,
    audio_minutes: 0,
    actual_rupees: rows.actual,
    expected_rupees: rows.expected,
    ratio,
    drifting: ratio !== null && Math.abs(ratio - 1) > 0.25,
    tokens: {
      actual_in: inActual,
      actual_out: outActual,
      expected_in: rows.tokens ? inExpected : null,
      expected_out: rows.tokens ? outExpected : null,
      ratio_in: rows.tokens
        ? Math.round((inActual / inExpected) * 1000) / 1000
        : null,
      ratio_out: rows.tokens
        ? Math.round((outActual / outExpected) * 1000) / 1000
        : null,
    },
  };
};

const PLAN_RATES: Record<string, number> = {
  today: 0.752,
  "today-brain4-read": 0.948,
  v2: 0.897,
  "v2-report-on-demand": 0.671,
  "v2-flex-report-on-demand": 0.339,
  "v2-luna-flex-report-on-demand": 0.161,
  "v2-luna-flex-compact": 0.119,
};

export function engineFixture(
  now: Date,
  state: "live" | "stale" | "empty" = "live",
) {
  const ago = (hours: number) =>
    new Date(now.getTime() - hours * 3_600_000).toISOString();
  const empty = state === "empty";
  return {
    environment: "production",
    available: !empty,
    generated_at: empty ? null : ago(state === "stale" ? 3 : 0.05),
    age_seconds: empty ? null : state === "stale" ? 3 * 3600 : 180,
    days: 7,
    since: ago(24 * 7),
    drift: 0.25,
    registry: REGISTRY,
    window: {
      calls: 31,
      analysed: 18,
      short: 13,
      audio_minutes: 141.6,
      actual_rupees: 118.94,
      expected_rupees: 104.12,
      actual_per_minute: 0.84,
      expected_per_minute: 0.735,
    },
    modules: [
      moduleRow("c1.audio-check", "Audio check", "C1", {
        calls: 31,
        steps: 31,
        actual: 0,
        expected: 0,
      }),
      moduleRow("c2.flash-lite", "Transcript · Gemini 3.1 Flash-Lite", "C2", {
        calls: 31,
        steps: 33,
        actual: 42.48,
        expected: 32.99,
      }),
      moduleRow(
        "c4.one-pass-v1",
        "One pass · facts, notes and 27-pointer review",
        "C4",
        {
          calls: 18,
          steps: 19,
          actual: 38.61,
          expected: 36.2,
          tokens: [118_400, 111_900, 79_800, 74_700],
        },
      ),
      moduleRow("c5.after-one-pass", "Full report · coaching-v5", "C5", {
        calls: 18,
        steps: 18,
        actual: 32.7,
        expected: 33.27,
      }),
      moduleRow(
        "pr.in-one-pass",
        "Pointer review · inside the one-pass read",
        "PR",
        {
          calls: 18,
          steps: 18,
          actual: 0,
          expected: 0,
        },
      ),
      moduleRow("cdf.fast", "Lead details · fast call data", "CDF", {
        calls: 13,
        steps: 13,
        actual: 0.61,
        expected: 0.66,
      }),
      moduleRow("C4·gpt-6-luna:flex", null, "C4", {
        calls: 2,
        steps: 2,
        actual: 0,
        expected: null,
        model: "gpt-6-luna:flex",
        unpriced: 2,
      }),
    ],
    plans: REGISTRY.plans.map((plan) => ({
      id: plan.id,
      label: plan.label,
      status: plan.status,
      window: {
        plan: plan.id,
        calls: 31,
        audio_minutes: 141.6,
        rupees: Math.round((PLAN_RATES[plan.id] ?? 0) * 141.6 * 100) / 100,
        per_minute: PLAN_RATES[plan.id] ?? null,
      },
    })),
    fx: { mode: "planning", planning_usd_to_inr: 100 },
    problems: [],
  };
}
