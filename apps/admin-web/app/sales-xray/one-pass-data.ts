/**
 * The one-pass trial (owner, 21 Oct 2026): this environment's analysis
 * pipeline switch (GET /v1/admin/analysis-pipeline) and the side-by-side
 * comparison of today's pipeline with the Google-only one-pass pipeline
 * (GET /v1/admin/analysis-pipeline/compare[/{subject}], one-pass-compare/1).
 * Pure normalizers: a missing or odd field gets a default, never a crash.
 * Rupees are list-price estimates for Admin only.
 */
import { read } from "../lib/read";

export type Choice = { value: string; label: string; whyNot: string | null };

export type PipelineSettings = {
  environment: string;
  revision: number | null;
  mode: string;
  transcriptionTier: string;
  analysisTier: string;
  maxCallMinutes: number;
  config: Record<string, unknown>;
  modes: Choice[];
  tiers: Choice[];
  models: { transcription: string; analysis: string };
  history: {
    revision: number;
    mode: string;
    reason: string | null;
    at: string;
  }[];
  recent: {
    subject: string;
    source: string;
    state: string;
    reason: string | null;
    costInr: number | null;
    durationMs: number | null;
    audioMs: number | null;
    contractsOk: number | null;
    at: string;
  }[];
};

const choices = (raw: unknown): Choice[] =>
  read.array(raw).map((item) => {
    const row = read.object(item);
    return {
      value: read.string(row.value),
      label: read.string(row.label, read.string(row.value)),
      whyNot: read.optionalString(row.why_not),
    };
  });

export function normalizePipeline(raw: unknown): PipelineSettings {
  const body = read.object(raw);
  const config = read.object(body.config);
  const models = read.object(body.models);
  return {
    environment: read.string(body.environment, "development"),
    revision: read.optionalNumber(body.revision),
    mode: read.string(config.mode, "classic"),
    transcriptionTier: read.string(config.transcription_tier, "standard"),
    analysisTier: read.string(config.analysis_tier, "standard"),
    maxCallMinutes: read.number(config.max_call_minutes, 60),
    config,
    modes: choices(body.modes),
    tiers: choices(body.tiers),
    models: {
      transcription: read.string(models.transcription),
      analysis: read.string(models.analysis),
    },
    history: read.array(body.history).map((item) => {
      const row = read.object(item);
      return {
        revision: read.number(row.revision),
        mode: read.string(read.object(row.config).mode, "classic"),
        reason: read.optionalString(row.reason),
        at: read.string(row.at),
      };
    }),
    recent: read.array(body.recent).map((item) => {
      const row = read.object(item);
      return {
        subject: read.string(row.subject),
        source: read.string(row.source),
        state: read.string(row.state),
        reason: read.optionalString(row.reason),
        costInr: read.optionalNumber(row.cost_inr),
        durationMs: read.optionalNumber(row.duration_ms),
        audioMs: read.optionalNumber(row.audio_ms),
        contractsOk: read.optionalNumber(row.contracts_ok),
        at: read.string(row.at),
      };
    }),
  };
}

export type SideSummary = {
  costInr: number | null;
  perMinuteInr: number | null;
  standardPerMinuteInr: number | null;
  flexPerMinuteInr: number | null;
  medianMs: number | null;
  factRecall: number | null;
  truthCoverage: number | null;
  contractsPassed: number | null;
  contractsChecked: number | null;
};

export type Summary = {
  calls: number;
  audioMinutes: number;
  classic: SideSummary;
  onePass: SideSummary;
  agreement: {
    factOverlap: number | null;
    pointerStatus: number | null;
    pointerScoreGap: number | null;
    dimensionStatus: number | null;
    transcriptVocabulary: number | null;
  };
};

const side = (raw: unknown): SideSummary => {
  const row = read.object(raw);
  return {
    costInr: read.optionalNumber(row.cost_inr),
    perMinuteInr: read.optionalNumber(row.per_minute_inr),
    standardPerMinuteInr: read.optionalNumber(row.standard_per_minute_inr),
    flexPerMinuteInr: read.optionalNumber(row.flex_per_minute_inr),
    medianMs: read.optionalNumber(row.median_ms),
    factRecall: read.optionalNumber(row.fact_recall),
    truthCoverage: read.optionalNumber(row.truth_coverage),
    contractsPassed: read.optionalNumber(row.contracts_passed),
    contractsChecked: read.optionalNumber(row.contracts_checked),
  };
};

export function normalizeSummary(raw: unknown): Summary {
  const row = read.object(raw);
  const agreement = read.object(row.agreement);
  return {
    calls: read.number(row.calls),
    audioMinutes: read.number(row.audio_minutes),
    classic: side(row.classic),
    onePass: side(row.one_pass),
    agreement: {
      factOverlap: read.optionalNumber(agreement.fact_overlap),
      pointerStatus: read.optionalNumber(agreement.pointer_status),
      pointerScoreGap: read.optionalNumber(agreement.pointer_score_gap),
      dimensionStatus: read.optionalNumber(agreement.dimension_status),
      transcriptVocabulary: read.optionalNumber(
        agreement.transcript_vocabulary,
      ),
    },
  };
}

export type CompareLine = {
  kind: "call" | "bench";
  subject: string;
  audioMs: number | null;
  classic: {
    state: string | null;
    costInr: number | null;
    durationMs: number | null;
  };
  onePass: {
    state: string | null;
    reason: string | null;
    costInr: number | null;
    flexCostInr: number | null;
    durationMs: number | null;
    contractsOk: number;
    at: string | null;
  };
  factOverlap: number | null;
  pointerAgreement: number | null;
  dimensionAgreement: number | null;
};

export type CompareList = {
  environment: string;
  calls: Summary;
  bench: Summary;
  items: CompareLine[];
};

export function normalizeCompareList(raw: unknown): CompareList {
  const body = read.object(raw);
  const summary = read.object(body.summary);
  return {
    environment: read.string(body.environment, "development"),
    calls: normalizeSummary(summary.calls),
    bench: normalizeSummary(summary.bench),
    items: read.array(body.items).map((item) => {
      const row = read.object(item);
      const subject = read.object(row.subject);
      const classic = read.object(row.classic);
      const one = read.object(row.one_pass);
      const kind = read.string(subject.kind) === "bench" ? "bench" : "call";
      return {
        kind,
        subject:
          kind === "bench"
            ? read.string(subject.call)
            : read.string(subject.recording_id),
        audioMs: read.optionalNumber(row.audio_ms),
        classic: {
          state: read.optionalString(classic.state),
          costInr: read.optionalNumber(classic.cost_inr),
          durationMs: read.optionalNumber(classic.duration_ms),
        },
        onePass: {
          state: read.optionalString(one.state),
          reason: read.optionalString(one.reason),
          costInr: read.optionalNumber(one.cost_inr),
          flexCostInr: read.optionalNumber(one.flex_cost_inr),
          durationMs: read.optionalNumber(one.duration_ms),
          contractsOk: read.number(one.contracts_ok),
          at: read.optionalString(one.at),
        },
        factOverlap: read.optionalNumber(row.fact_overlap),
        pointerAgreement: read.optionalNumber(row.pointer_agreement),
        dimensionAgreement: read.optionalNumber(row.dimension_agreement),
      };
    }),
  };
}

export type Stage = {
  key: string;
  label: string;
  inr: number | null;
  tokensIn: number | null;
  tokensOut: number | null;
  ms: number | null;
  model: string | null;
  tier: string | null;
  note: string | null;
};

export type Fact = {
  type: string;
  label: string;
  display: string;
  confidence: number | null;
};

export type Side = {
  pipeline: string;
  available: boolean;
  state: string | null;
  reason: string | null;
  audioMs: number | null;
  costInr: number | null;
  perMinuteInr: number | null;
  flexCostInr: number | null;
  standardCostInr: number | null;
  durationMs: number | null;
  tokensIn: number;
  tokensOut: number;
  stages: Stage[];
  transcript: {
    source: string;
    segments: number;
    speakers: number;
    words: number;
    rows: { id: string; speaker: string; startMs: number; text: string }[];
  } | null;
  facts: Fact[];
  c4Observations: number | null;
  pointers: {
    overall: number | null;
    line: string | null;
    rows: { id: string; label: string; status: string; score: number | null }[];
  } | null;
  coaching: {
    summary: string | null;
    verdict: string | null;
    strengths: string[];
    improvements: string[];
    missed: string[];
    objections: string[];
    closing: string[];
    dimensions: { id: string; status: string }[];
  } | null;
  checks: Record<string, string> | null;
  judge: { factRecall: number | null; truthCoverage: number | null } | null;
};

function normalizeSide(raw: unknown): Side | null {
  if (!raw || typeof raw !== "object") return null;
  const row = read.object(raw);
  const transcript = row.transcript ? read.object(row.transcript) : null;
  const pointers = row.pointers ? read.object(row.pointers) : null;
  const coaching = row.coaching ? read.object(row.coaching) : null;
  const judge = row.judge ? read.object(row.judge) : null;
  const checks = row.checks ? read.object(row.checks) : null;
  return {
    pipeline: read.string(row.pipeline),
    available: read.boolean(row.available),
    state: read.optionalString(row.state),
    reason: read.optionalString(row.reason),
    audioMs: read.optionalNumber(row.audio_ms),
    costInr: read.optionalNumber(row.cost_inr),
    perMinuteInr: read.optionalNumber(row.per_minute_inr),
    flexCostInr: read.optionalNumber(row.flex_cost_inr),
    standardCostInr: read.optionalNumber(row.standard_cost_inr),
    durationMs: read.optionalNumber(row.duration_ms),
    tokensIn: read.number(row.tokens_in),
    tokensOut: read.number(row.tokens_out),
    stages: read.array(row.stages).map((item) => {
      const stage = read.object(item);
      return {
        key: read.string(stage.key),
        label: read.string(stage.label, read.string(stage.key)),
        inr: read.optionalNumber(stage.inr),
        tokensIn: read.optionalNumber(stage.tokens_in),
        tokensOut: read.optionalNumber(stage.tokens_out),
        ms: read.optionalNumber(stage.ms),
        model: read.optionalString(stage.model),
        tier: read.optionalString(stage.tier),
        note: read.optionalString(stage.note),
      };
    }),
    transcript: transcript
      ? {
          source: read.string(transcript.source),
          segments: read.number(transcript.segments),
          speakers: read.number(transcript.speakers),
          words: read.number(transcript.words),
          rows: read.array(transcript.rows).map((item) => {
            const line = read.object(item);
            return {
              id: read.string(line.id),
              speaker: read.string(line.speaker),
              startMs: read.number(line.start_ms),
              text: read.string(line.text),
            };
          }),
        }
      : null,
    facts: read.array(row.objects).map((item) => {
      const fact = read.object(item);
      return {
        type: read.string(fact.type),
        label: read.string(fact.label, read.string(fact.type)),
        display: read.string(fact.display),
        confidence: read.optionalNumber(fact.confidence),
      };
    }),
    c4Observations: read.optionalNumber(row.c4_observations),
    pointers: pointers
      ? {
          overall: read.optionalNumber(pointers.overall),
          line: read.optionalString(pointers.line),
          rows: read.array(pointers.rows).map((item) => {
            const p = read.object(item);
            return {
              id: read.string(p.id),
              label: read.string(p.label, read.string(p.id)),
              status: read.string(p.status),
              score: read.optionalNumber(p.score),
            };
          }),
        }
      : null,
    coaching: coaching
      ? {
          summary: read.optionalString(coaching.summary),
          verdict: read.optionalString(coaching.verdict),
          strengths: read.strings(coaching.strengths),
          improvements: read.strings(coaching.improvements),
          missed: read.strings(coaching.missed_opportunities),
          objections: read.strings(coaching.objections),
          closing: read.strings(coaching.closing),
          dimensions: read.array(coaching.dimensions).map((item) => {
            const d = read.object(item);
            return { id: read.string(d.id), status: read.string(d.status) };
          }),
        }
      : null,
    checks: checks
      ? Object.fromEntries(
          Object.entries(checks).map(([key, value]) => [
            key,
            read.string(value),
          ]),
        )
      : null,
    judge: judge
      ? {
          factRecall: read.optionalNumber(judge.fact_recall),
          truthCoverage: read.optionalNumber(judge.truth_coverage),
        }
      : null,
  };
}

export type Compared = {
  environment: string;
  kind: "call" | "bench";
  subject: string;
  classic: Side | null;
  onePass: Side | null;
  costSavingInr: number | null;
  costRatio: number | null;
  timeRatio: number | null;
  facts: {
    both: { type: string; label: string; classic: string; onePass: string }[];
    onlyClassic: Fact[];
    onlyOnePass: Fact[];
    overlap: number | null;
  } | null;
  pointers: {
    rows: {
      id: string;
      label: string;
      classic: { status: string; score: number | null };
      onePass: { status: string; score: number | null };
      same: boolean;
    }[];
    agreement: number | null;
    meanScoreGap: number | null;
    overallDifference: number | null;
  } | null;
  dimensions: { id: string; classic: string; onePass: string | null }[];
  dimensionAgreement: number | null;
  transcript: {
    wordRatio: number | null;
    vocabularyOverlap: number | null;
  } | null;
};

const facts = (raw: unknown): Fact[] =>
  read.array(raw).map((item) => {
    const fact = read.object(item);
    return {
      type: read.string(fact.type),
      label: read.string(fact.label, read.string(fact.type)),
      display: read.string(fact.display),
      confidence: read.optionalNumber(fact.confidence),
    };
  });

const status = (raw: unknown) => {
  const row = read.object(raw);
  return {
    status: read.string(row.status),
    score: read.optionalNumber(row.score),
  };
};

export function normalizeCompared(raw: unknown): Compared {
  const body = read.object(raw);
  const subject = read.object(body.subject);
  const kind = read.string(subject.kind) === "bench" ? "bench" : "call";
  const differences = read.object(body.differences);
  const factDiff = differences.facts ? read.object(differences.facts) : null;
  const pointerDiff = differences.pointers
    ? read.object(differences.pointers)
    : null;
  const coaching = read.object(differences.coaching);
  const transcript = differences.transcript
    ? read.object(differences.transcript)
    : null;
  return {
    environment: read.string(body.environment, "development"),
    kind,
    subject:
      kind === "bench"
        ? read.string(subject.call)
        : read.string(subject.recording_id),
    classic: normalizeSide(body.classic),
    onePass: normalizeSide(body.one_pass),
    costSavingInr: read.optionalNumber(differences.cost_saving_inr),
    costRatio: read.optionalNumber(differences.cost_ratio),
    timeRatio: read.optionalNumber(differences.time_ratio),
    facts: factDiff
      ? {
          both: read.array(factDiff.both).map((item) => {
            const row = read.object(item);
            return {
              type: read.string(row.type),
              label: read.string(row.label, read.string(row.type)),
              classic: read.string(row.classic),
              onePass: read.string(row.one_pass),
            };
          }),
          onlyClassic: facts(factDiff.only_classic),
          onlyOnePass: facts(factDiff.only_one_pass),
          overlap: read.optionalNumber(factDiff.overlap),
        }
      : null,
    pointers: pointerDiff
      ? {
          rows: read.array(pointerDiff.rows).map((item) => {
            const row = read.object(item);
            return {
              id: read.string(row.id),
              label: read.string(row.label, read.string(row.id)),
              classic: status(row.classic),
              onePass: status(row.one_pass),
              same: read.boolean(row.same_status),
            };
          }),
          agreement: read.optionalNumber(pointerDiff.agreement),
          meanScoreGap: read.optionalNumber(pointerDiff.mean_score_gap),
          overallDifference: read.optionalNumber(
            pointerDiff.overall_difference,
          ),
        }
      : null,
    dimensions: read.array(coaching.dimensions).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.id),
        classic: read.string(row.classic),
        onePass: read.optionalString(row.one_pass),
      };
    }),
    dimensionAgreement: read.optionalNumber(coaching.dimension_agreement),
    transcript: transcript
      ? {
          wordRatio: read.optionalNumber(transcript.word_ratio),
          vocabularyOverlap: read.optionalNumber(transcript.vocabulary_overlap),
        }
      : null,
  };
}

/** "₹1.19" (two decimals), or an empty string when unknown. */
export const inr = (value: number | null | undefined) =>
  value === null || value === undefined ? "" : `₹${value.toFixed(2)}`;

/** "73%" for a 0–1 share, or "—". */
export const share = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;

/** "1 min 05 s", "42 s", or "—". */
export function took(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${String(seconds % 60).padStart(2, "0")} s`;
}

export const CONTRACTS: readonly { key: string; label: string }[] = [
  { key: "c2", label: "Transcript (C2)" },
  { key: "c4", label: "Facts (C4)" },
  { key: "c5", label: "Report and coaching (C5)" },
  { key: "pointer_review", label: "Pointer review" },
  { key: "call_objects", label: "Call objects" },
  { key: "prospect_facts", label: "Prospect facts" },
];
