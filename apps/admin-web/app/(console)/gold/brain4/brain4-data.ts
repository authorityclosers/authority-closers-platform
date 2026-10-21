/**
 * Brain 4.0 against the gold set (GET /v1/admin/conversation/gold-evaluation,
 * brain4_eval.py): counts, labels and agreement only, never a reviewer's note
 * or the call's words. Every field has a default, so an older server or a
 * missing figure shows as "—" instead of breaking the page.
 */
import { z } from "zod";

const interval = z
  .tuple([z.number(), z.number()])
  .nullable()
  .catch(null)
  .default(null);
const rate = z.number().nullable().catch(null).default(null);

const agreement = z
  .object({
    lines: z.number().catch(0).default(0),
    calls: z.number().catch(0).default(0),
    banded: z.number().catch(0).default(0),
    exact: rate,
    exact_ci: interval,
    within_one: rate,
    kappa: rate,
    kappa_ci: interval,
    band_error: rate,
    lean: rate,
    judgeable_agree: rate,
    direction_right: rate,
    directions: z.number().catch(0).default(0),
  })
  .catch({
    lines: 0,
    calls: 0,
    banded: 0,
    exact: null,
    exact_ci: null,
    within_one: null,
    kappa: null,
    kappa_ci: null,
    band_error: null,
    lean: null,
    judgeable_agree: null,
    direction_right: null,
    directions: 0,
  });

const acceptance = z.object({
  lines: z.number().catch(0).default(0),
  calls: z.number().catch(0).default(0),
  skipped: z.number().catch(0).default(0),
  agree: z.number().catch(0).default(0),
  partly: z.number().catch(0).default(0),
  disagree: z.number().catch(0).default(0),
  agree_rate: rate,
  agree_ci: interval,
  reasons: z.record(z.string(), z.number()).catch({}).default({}),
});

const drop = z
  .object({ before: z.number(), recent: z.number(), alert: z.boolean() })
  .nullable()
  .catch(null)
  .default(null);

const checkpointRate = z
  .object({
    labels: z.number().catch(0).default(0),
    rated: z.number().catch(0).default(0),
    agree: z.number().catch(0).default(0),
    agreement: rate,
    wilson: interval,
  })
  .catch({ labels: 0, rated: 0, agree: 0, agreement: null, wilson: null });

/** A fixed evaluation on an earlier gold set (gold v1: the coaching lead's doc). */
const checkpoint = z.object({
  checkpoint: z.string(),
  title: z.string().catch("").default(""),
  date: z.string().catch("").default(""),
  source: z.string().catch("").default(""),
  calls: z.number().catch(0).default(0),
  notes_mapped: z.number().catch(0).default(0),
  labels: z.record(z.string(), z.number()).catch({}).default({}),
  scorers: z
    .array(
      z.object({
        scorer: z.string(),
        repeat_same: rate,
        reads_per_call: z.number().catch(1).default(1),
        overall: checkpointRate,
        by_label: z.record(z.string(), checkpointRate).catch({}).default({}),
        dimensions: z.record(z.string(), checkpointRate).catch({}).default({}),
      }),
    )
    .catch([])
    .default([]),
  limits: z.array(z.string()).catch([]).default([]),
});

export type Checkpoint = z.infer<typeof checkpoint>;

const count = z.number().catch(0).default(0);
const readiness = z
  .object({
    state: z.string().catch("needs_data").default("needs_data"),
    needs: z.array(z.string()).catch([]).default([]),
  })
  .catch({ state: "needs_data", needs: [] });

/** Brain 4.0's rating against a blind rating, on the 1-5 scale. */
const ratingAgreement = z.object({
  lines: count,
  calls: count,
  rated: count,
  exact: rate,
  exact_ci: interval,
  within_one: rate,
  within_one_ci: interval,
  kappa: rate,
  kappa_ci: interval,
  band_error: rate,
  lean: rate,
  judgeable_agree: rate,
});

/** Blind ratings (AC-SVAL-01 section 8.1), two raters (Gate 0) and moments. */
const blindSchema = z.object({
  ratings: count,
  calls: count,
  calls_with_brain4: count,
  reviewers: count,
  dimensions: z
    .array(
      z.object({
        id: z.string(),
        label: z.string().catch("").default(""),
        category: z.string().catch("").default(""),
        ratings: count,
        brain4: ratingAgreement.catch(ratingAgreement.parse({})),
        readiness,
        undecidable: z.string().nullable().catch(null).default(null),
        drop,
      }),
    )
    .catch([])
    .default([]),
  between_raters: z
    .object({
      calls: count,
      pairs: count,
      rated: count,
      exact: rate,
      kappa: rate,
      gate0: z.boolean().catch(false).default(false),
    })
    .catch({
      calls: 0,
      pairs: 0,
      rated: 0,
      exact: null,
      kappa: null,
      gate0: false,
    }),
  moments: z
    .object({
      moments: count,
      criticisms: count,
      praise: count,
      written_blind: count,
      marked: count,
      caught: z.record(z.string(), z.number()).catch({}).default({}),
      caught_rate: rate,
      caught_ci: interval,
      by_dimension: z
        .array(
          z.object({
            id: z.string(),
            criticisms: count,
            marked: count,
            caught_rate: rate,
          }),
        )
        .catch([])
        .default([]),
    })
    .catch({
      moments: 0,
      criticisms: 0,
      praise: 0,
      written_blind: 0,
      marked: 0,
      caught: {},
      caught_rate: null,
      caught_ci: null,
      by_dimension: [],
    }),
});

const progressCount = z
  .object({ want: count, have: count })
  .catch({ want: 0, have: 0 });

/** The gold checkpoint's chosen sample so far (gold_checkpoint.py). */
const sampleSchema = z.object({
  name: z.string().catch("").default(""),
  mode: z.string().catch("").default(""),
  since: z.string().catch("").default(""),
  minutes: z
    .tuple([z.number(), z.number()])
    .nullable()
    .catch(null)
    .default(null),
  workspaces: z.string().catch("").default(""),
  daily: count,
  total: count,
  chosen: count,
  salespeople: count,
  at_least: z.record(z.string(), progressCount).catch({}).default({}),
  mix: z.record(z.string(), progressCount).catch({}).default({}),
});

export type Blind = z.infer<typeof blindSchema>;
export type Sample = z.infer<typeof sampleSchema>;

export const brain4Evaluation = z.object({
  version: z.string().catch("").default(""),
  generated_at: z.string().catch("").default(""),
  brain4_version: z.string().catch("").default(""),
  rubric_revision: z.string().catch("").default(""),
  gold: z
    .object({
      lines: z.number().catch(0).default(0),
      calls: z.number().catch(0).default(0),
      calls_with_brain4: z.number().catch(0).default(0),
      first: z.string().nullable().catch(null).default(null),
      last: z.string().nullable().catch(null).default(null),
    })
    .catch({
      lines: 0,
      calls: 0,
      calls_with_brain4: 0,
      first: null,
      last: null,
    }),
  classic_acceptance: acceptance.catch(acceptance.parse({})),
  classic_drop: drop,
  pointers: z
    .array(acceptance.extend({ target: z.string() }))
    .catch([])
    .default([]),
  dimensions: z
    .array(
      z.object({
        id: z.string(),
        label: z.string().catch("").default(""),
        category: z.string().catch("").default(""),
        pointers: z.array(z.string()).catch([]).default([]),
        brain4: agreement,
        classic: agreement,
        readiness,
        undecidable: z.string().nullable().catch(null).default(null),
        drop,
      }),
    )
    .catch([])
    .default([]),
  blind: blindSchema.catch(blindSchema.parse({})),
  sample: sampleSchema.nullable().catch(null).default(null),
  stability: z
    .record(z.string(), z.object({ calls: z.number(), same: z.number() }))
    .catch({})
    .default({}),
  alerts: z
    .array(
      z.object({
        scorer: z.string(),
        dimension: z.string().nullable().catch(null).default(null),
        before: z.number(),
        recent: z.number(),
      }),
    )
    .catch([])
    .default([]),
  limits: z.array(z.string()).catch([]).default([]),
  checkpoints: z.array(checkpoint).catch([]).default([]),
});

export type Brain4Evaluation = z.infer<typeof brain4Evaluation>;
export type Agreement = z.infer<typeof agreement>;

export function normalizeBrain4(body: unknown): Brain4Evaluation {
  return brain4Evaluation.parse(body ?? {});
}

/** "62%" for 0.62; "—" when there is nothing to show. */
export function percent(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value * 100)}%`
    : "—";
}

/** "62% (48–74%)": the figure with its 95% interval over whole calls. */
export function withInterval(
  value: number | null,
  bounds: readonly [number, number] | null,
  format: (n: number | null) => string = percent,
): string {
  if (value === null) return "—";
  return bounds
    ? `${format(value)} (${format(bounds[0])}–${format(bounds[1])})`
    : format(value);
}

export function decimal(value: number | null | undefined, digits = 2): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—";
}

/** A signed band difference: "+0.40 (more generous)" or "−0.25 (stricter)". */
export function lean(value: number | null): string {
  if (value === null) return "—";
  if (Math.abs(value) < 0.005) return "0.00";
  const sign = value > 0 ? "+" : "−";
  const word = value > 0 ? "more generous" : "stricter";
  return `${sign}${Math.abs(value).toFixed(2)} (${word})`;
}

export const READINESS: Record<
  string,
  { label: string; tone: "neutral" | "info" | "good" | "warn" }
> = {
  needs_data: { label: "Needs gold data", tone: "neutral" },
  beta: { label: "Beta", tone: "warn" },
  gate3_candidate: { label: "Gate 3 candidate", tone: "info" },
  undecidable: { label: "Undecidable for now", tone: "neutral" },
};

/** What the checkpoint's counts are called on the page. */
export const SAMPLE_WORDS: Record<string, string> = {
  price: "reach price or closing",
  objection: "raise an objection",
  decision: "talk decisions or next steps",
  first_call: "first calls",
  follow_up: "follow-ups",
  won: "won",
  lost: "lost",
  pending: "pending",
};

export const CATEGORY_LABELS: Record<string, string> = {
  how_you_talk: "How You Talk",
  understanding_the_buyer: "How Well You Understand the Buyer",
  moving_the_sale_forward: "How Well You Move the Sale Forward",
};

/** "4/6" for a rate, "—" when nothing was compared. */
export function ratio(value: { agree: number; rated: number }): string {
  return value.rated ? `${value.agree}/${value.rated}` : "—";
}
