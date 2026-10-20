/**
 * One call's stage map (GET /v1/admin/conversation/calls/{id}/data-map,
 * call data engine, owner 19 Oct): received → C1 audio check → C2 transcript
 * → fast pipeline → call objects → better transcript → deep pipeline →
 * objects updated; C3 alignment → C4 facts → C5 report and coaching → C6
 * published → AI pointer review, Prospect; human review. Normalizers give
 * every missing field a default. Pure.
 */
import { read } from "../lib/read";

export const STAGE_STATUSES = [
  "done",
  "running",
  "failed",
  "skipped",
  "waiting",
  "not_built",
] as const;
export type StageStatus = (typeof STAGE_STATUSES)[number];

export const STAGE_STATUS_LABEL: Record<StageStatus, string> = {
  done: "Done",
  running: "Running",
  failed: "Failed",
  skipped: "Skipped",
  waiting: "Waiting",
  not_built: "Not built yet",
};

export const STAGE_STATUS_TONE: Record<
  StageStatus,
  "good" | "accent" | "bad" | "neutral" | "warn"
> = {
  done: "good",
  running: "accent",
  failed: "bad",
  skipped: "neutral",
  waiting: "neutral",
  not_built: "neutral",
};

export type MapStage = {
  key: string;
  label: string;
  /** The main analysis stage, C1 to C6; null for the others. */
  code: string | null;
  status: StageStatus;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  costInr: number | null;
  provider: string | null;
  model: string | null;
  version: string | null;
  detail: string | null;
  counts: Record<string, unknown>;
};

export type CallMapData = {
  recordingId: string;
  submissionId: string | null;
  workspace: string;
  state: string;
  mediaMs: number | null;
  stages: MapStage[];
  costInr: number;
};

const asStatus = (value: unknown): StageStatus =>
  STAGE_STATUSES.includes(value as StageStatus)
    ? (value as StageStatus)
    : "waiting";

export function normalizeMap(raw: unknown): CallMapData {
  const body = read.object(raw);
  return {
    recordingId: read.string(body.recording_id),
    submissionId: read.optionalString(body.submission_id),
    workspace: read.string(body.workspace, "Unknown workspace"),
    state: read.string(body.state),
    mediaMs: read.optionalNumber(body.media_ms),
    costInr: read.number(body.cost_inr),
    stages: read.array(body.stages).map((item) => {
      const stage = read.object(item);
      return {
        key: read.string(stage.key),
        label: read.string(stage.label, "Stage"),
        code: read.optionalString(stage.code),
        status: asStatus(stage.status),
        startedAt: read.optionalString(stage.started_at),
        finishedAt: read.optionalString(stage.finished_at),
        durationMs: read.optionalNumber(stage.duration_ms),
        costInr: read.optionalNumber(stage.cost_inr),
        provider: read.optionalString(stage.provider),
        model: read.optionalString(stage.model),
        version: read.optionalString(stage.version),
        detail: read.optionalString(stage.detail),
        counts: read.object(stage.counts),
      };
    }),
  };
}

/** 850 ms, 12.4 s, 3 min 05 s. */
export function duration(ms: number | null): string {
  if (ms === null) return "";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

/** ₹0.45, ₹12.30; under one paisa reads as "under ₹0.01". */
export function rupees(value: number | null): string {
  if (value === null) return "";
  if (value > 0 && value < 0.01) return "under ₹0.01";
  return `₹${value.toFixed(2)}`;
}

/** The one-line "who and what" under a stage. */
export function stageMeta(stage: MapStage): string {
  return [stage.provider, stage.model, stage.version]
    .filter(Boolean)
    .join(" · ");
}

/** Counts worth showing, in words (call objects and fast-pipeline tokens). */
export function stageCounts(stage: MapStage): string[] {
  const counts = stage.counts;
  const words: string[] = [];
  const number = (key: string) => read.optionalNumber(counts[key]);
  if (stage.key === "objects" || stage.key === "objects_updated") {
    const objects = number("objects");
    if (objects !== null) words.push(`${objects} facts`);
    for (const [key, label] of [
      ["auto_filled", "filled"],
      ["asked", "asked"],
      ["accepted", "kept"],
      ["edited", "changed"],
      ["rejected", "rejected"],
    ] as const) {
      const value = number(key);
      if (value) words.push(`${value} ${label}`);
    }
    for (const [key, label] of [
      ["superseded", "superseded"],
      ["retracted", "retracted"],
    ] as const) {
      const value = number(key);
      if (value) words.push(`${value} ${label}`);
    }
    const categories = read.object(counts.by_category);
    const top = Object.entries(categories)
      .filter(
        (entry): entry is [string, number] => typeof entry[1] === "number",
      )
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => `${name} ${count}`);
    if (top.length) words.push(top.join(", "));
  }
  if (stage.key === "deep") {
    const labelled = number("segments_labelled");
    if (labelled) words.push(`${labelled} segments labelled`);
    const audio = read.optionalString(counts.audio);
    if (audio)
      words.push(
        audio === "frames" ? "voice from audio frames" : "voice from timings",
      );
  }
  if (["fast", "deep", "facts", "coaching"].includes(stage.key)) {
    const inTokens = number("tokens_in");
    const outTokens = number("tokens_out");
    if (inTokens !== null && outTokens !== null)
      words.push(
        `${inTokens.toLocaleString("en-IN")} in / ${outTokens.toLocaleString("en-IN")} out tokens`,
      );
    const attempts = number("attempts");
    if (attempts && attempts > 1) words.push(`${attempts} attempts`);
  }
  if (stage.key === "report") {
    const chunks = number("fact_chunks");
    if (chunks) words.push(`${chunks} fact chunk${chunks === 1 ? "" : "s"}`);
  }
  return words;
}
