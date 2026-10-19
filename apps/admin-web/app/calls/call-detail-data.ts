/**
 * One call, everything the engine knows (GET /v1/admin/call-data/calls/{id}/
 * detail, call-data-detail/1, call data engine, owner 19 Oct: "all data for
 * making it better has to be there"): the call, every stage and the links
 * between them, every engine run, every object ever made (current, superseded,
 * retracted, erased) with its decisions, totals per branch, and the facts,
 * segments and voice the engine-objects view draws. Defaults everywhere. Pure.
 */
import { read } from "../lib/read";
import { asKind, type WorkspaceKind } from "../lib/workspaces";
import { STAGE_STATUSES, type StageStatus } from "./call-map-data";
import {
  normalizeEngineObjects,
  type EngineObjects,
} from "./engine-objects-data";

export type Branch = "main" | "fast" | "deep" | "report";
const BRANCHES: readonly Branch[] = ["main", "fast", "deep", "report"];

export type DetailStage = {
  key: string;
  label: string;
  status: StageStatus;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  costInr: number | null;
  provider: string | null;
  model: string | null;
  version: string | null;
  detail: string | null;
  attempts: number | null;
  tokensIn: number | null;
  tokensOut: number | null;
};

export type DetailEdge = {
  from: string;
  to: string;
  branch: Branch;
  status: StageStatus;
  costInr: number | null;
  durationMs: number | null;
};

export type DetailRun = {
  runId: string;
  pipeline: string;
  version: string | null;
  taxonomyVersion: string | null;
  trigger: string | null;
  state: string;
  reason: string | null;
  provider: string | null;
  model: string | null;
  promptSha: string | null;
  tokensIn: number | null;
  tokensOut: number | null;
  costInr: number | null;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  attempt: number | null;
};

export type ObjectState = "current" | "superseded" | "retracted" | "erased";

export type DetailDecision = {
  decision: string;
  actor: string | null;
  at: string | null;
  question: string | null;
  leadField: string | null;
  leadWritten: boolean;
};

export type DetailObject = {
  objectId: string;
  type: string;
  category: string;
  display: string;
  confidence: number | null;
  basis: string | null;
  pipeline: string | null;
  version: string | null;
  runId: string | null;
  supersedesId: string | null;
  state: ObjectState;
  createdAt: string | null;
  decisions: DetailDecision[];
};

export type Totals = { costInr: number; tokensIn: number; tokensOut: number };

/** A moment the engine heard a fact: offsets in ms from the start of the call. */
export type Evidence = {
  startMs: number;
  endMs: number | null;
  quote: string | null;
  speaker: string | null;
};

export type CallDetail = {
  call: {
    recordingId: string;
    state: string;
    mediaMs: number | null;
    costInr: number;
    organisation: { id: string; name: string; kind: WorkspaceKind };
    rep: { label: string; email: string | null };
    language: string | null;
    environment: string | null;
  };
  stages: DetailStage[];
  edges: DetailEdge[];
  runs: DetailRun[];
  objects: DetailObject[];
  totals: Record<Branch | "call", Totals>;
  engine: EngineObjects;
  /** Each current fact's moments, by object id, earliest first. */
  evidence: Record<string, Evidence[]>;
  taxonomyVersion: string | null;
};

const status = (value: unknown): StageStatus =>
  STAGE_STATUSES.includes(value as StageStatus)
    ? (value as StageStatus)
    : "waiting";

const branch = (value: unknown): Branch =>
  BRANCHES.includes(value as Branch) ? (value as Branch) : "main";

const n = read.optionalNumber;
const s = read.optionalString;

function totals(raw: unknown): Totals {
  const value = read.object(raw);
  return {
    costInr: read.number(value.cost_inr),
    tokensIn: read.number(value.tokens_in),
    tokensOut: read.number(value.tokens_out),
  };
}

function objectState(row: Record<string, unknown>): ObjectState {
  if (row.erased === true) return "erased";
  if (row.retracted === true) return "retracted";
  if (row.current === false) return "superseded";
  return "current";
}

function evidenceByFact(raw: unknown): Record<string, Evidence[]> {
  const found: Record<string, Evidence[]> = {};
  for (const item of read.array(raw)) {
    const fact = read.object(item);
    const moments = read
      .array(fact.evidence)
      .map((entry) => read.object(entry))
      .filter((entry) => typeof entry.start_ms === "number")
      .map((entry) => ({
        startMs: read.number(entry.start_ms),
        endMs: n(entry.end_ms),
        quote: s(entry.quote) ?? s(entry.text),
        speaker: s(entry.role) ?? s(entry.speaker),
      }))
      .sort((a, b) => a.startMs - b.startMs);
    if (moments.length) found[read.string(fact.object_id)] = moments;
  }
  return found;
}

export function normalizeCallDetail(raw: unknown): CallDetail {
  const body = read.object(raw);
  const call = read.object(body.call);
  const organisation = read.object(call.organisation);
  const rep = read.object(call.rep);
  const total = read.object(body.totals);
  return {
    call: {
      recordingId: read.string(call.recording_id),
      state: read.string(call.state),
      mediaMs: n(call.media_ms),
      costInr: read.number(call.cost_inr),
      organisation: {
        id: read.string(organisation.id, read.string(call.tenant_id)),
        name: read.string(
          organisation.name,
          read.string(call.workspace, "Unknown organisation"),
        ),
        kind: asKind(organisation.kind),
      },
      rep: { label: read.string(rep.label, "Unknown"), email: s(rep.email) },
      language: s(call.language),
      environment: s(call.environment),
    },
    stages: read.array(body.stages).map((item) => {
      const stage = read.object(item);
      return {
        key: read.string(stage.key),
        label: read.string(stage.label, read.string(stage.key, "Stage")),
        status: status(stage.status),
        startedAt: s(stage.started_at),
        finishedAt: s(stage.finished_at),
        durationMs: n(stage.duration_ms),
        costInr: n(stage.cost_inr),
        provider: s(stage.provider),
        model: s(stage.model),
        version: s(stage.version),
        detail: s(stage.detail),
        attempts: n(stage.attempts),
        tokensIn: n(stage.tokens_in),
        tokensOut: n(stage.tokens_out),
      };
    }),
    edges: read.array(body.edges).map((item) => {
      const edge = read.object(item);
      return {
        from: read.string(edge.from),
        to: read.string(edge.to),
        branch: branch(edge.branch),
        status: status(edge.status),
        costInr: n(edge.cost_inr),
        durationMs: n(edge.duration_ms),
      };
    }),
    runs: read.array(body.runs).map((item) => {
      const run = read.object(item);
      return {
        runId: read.string(run.run_id),
        pipeline: read.string(run.pipeline, "—"),
        version: s(run.version),
        taxonomyVersion: s(run.taxonomy_version),
        trigger: s(run.trigger),
        state: read.string(run.state, "unknown"),
        reason: s(run.reason),
        provider: s(run.provider),
        model: s(run.model),
        promptSha: s(run.prompt_sha256),
        tokensIn: n(run.tokens_in),
        tokensOut: n(run.tokens_out),
        costInr: n(run.cost_inr),
        startedAt: s(run.started_at),
        finishedAt: s(run.finished_at),
        durationMs: n(run.duration_ms),
        attempt: n(run.attempt),
      };
    }),
    objects: read.array(body.objects).map((item) => {
      const row = read.object(item);
      return {
        objectId: read.string(row.object_id),
        type: read.string(row.type, "object"),
        category: read.string(row.category),
        display: read.string(row.display),
        confidence: n(row.confidence),
        basis: s(row.basis),
        pipeline: s(row.pipeline),
        version: s(row.version),
        runId: s(row.run_id),
        supersedesId: s(row.supersedes_id),
        state: objectState(row),
        createdAt: s(row.created_at),
        decisions: read.array(row.decisions).map((entry) => {
          const decision = read.object(entry);
          return {
            decision: read.string(decision.decision),
            actor: s(decision.actor),
            at: s(decision.at),
            question: s(decision.question),
            leadField: s(decision.lead_field),
            leadWritten: decision.lead_written === true,
          };
        }),
      };
    }),
    totals: {
      call: totals(total.call),
      main: totals(total.main),
      fast: totals(total.fast),
      deep: totals(total.deep),
      report: totals(total.report),
    },
    engine: normalizeEngineObjects(body),
    evidence: evidenceByFact(body.facts),
    taxonomyVersion: s(body.taxonomy_version),
  };
}

/* ---------- The graph's layout ---------- */

/** Where each known stage sits: column left to right, lane top to bottom. */
export const LAYOUT: Readonly<Record<string, { col: number; lane: number }>> = {
  received: { col: 0, lane: 1 },
  audio_check: { col: 1, lane: 0 },
  transcription: { col: 1, lane: 1 },
  fast: { col: 2, lane: 1 },
  objects: { col: 3, lane: 1 },
  better_transcript: { col: 2, lane: 2 },
  deep: { col: 3, lane: 2 },
  objects_updated: { col: 4, lane: 2 },
  report: { col: 2, lane: 3 },
  pointer_review: { col: 3, lane: 3 },
  prospect: { col: 4, lane: 3 },
};

export const LANES = ["Checks", "Main · fast", "Deep read", "Report"] as const;

/** Stages with a place on the graph, and any new stage the layout doesn't know yet. */
export function placeStages(stages: readonly DetailStage[]) {
  const placed = stages.filter((stage) => stage.key in LAYOUT);
  const extra = stages.filter((stage) => !(stage.key in LAYOUT));
  return { placed, extra };
}

/** Objects grouped for the filter: how many of each type and state. */
export function objectFacets(objects: readonly DetailObject[]) {
  const types = new Map<string, number>();
  const states = new Map<ObjectState, number>();
  for (const object of objects) {
    types.set(object.type, (types.get(object.type) ?? 0) + 1);
    states.set(object.state, (states.get(object.state) ?? 0) + 1);
  }
  return {
    types: [...types.entries()].sort((a, b) => b[1] - a[1]),
    states: [...states.entries()],
  };
}
