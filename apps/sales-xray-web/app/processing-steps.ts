/**
 * The three steps a call moves through while it is analysed. The processing
 * plan's current stage (C0–C6) is the live truth; the submission's task rows
 * (C2, C4, C5) are the fallback when a server has no plan for the call.
 * Nothing here advances on a timer.
 */
import type { Progress, StageProgress } from "./acquisition-client";
import type { AcquisitionProcessingStageRow } from "./acquisition-processing-panel";

export const PROCESSING_STEPS = [
  {
    id: "C2",
    title: "Listening",
    description: "Writing down what was said, and who said it",
  },
  {
    id: "C4",
    title: "Understanding",
    description: "Finding key moments, objections and next steps",
  },
  {
    id: "C5",
    title: "Preparing your report",
    description: "Putting it all into your report",
  },
] as const;

export type StepState = "done" | "active" | "waiting" | "attention";

/** The plan as this screen needs it; anything unexpected reads as unknown. */
export type LivePlan = {
  state: string;
  stage: string | null;
  reportReady: boolean;
};

export function readLivePlan(value: unknown): LivePlan | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  if (typeof data.state !== "string") return null;
  const stage = data.current_stage;
  return {
    state: data.state,
    stage: typeof stage === "string" && /^C[0-6]$/.test(stage) ? stage : null,
    reportReady: data.report_ready === true,
  };
}

/** C0–C2 → Listening, C3–C4 → Understanding, C5–C6 → Preparing. */
export function stepIndexForStage(stage: string | null): number | null {
  const n = stage ? Number(stage.slice(1)) : NaN;
  if (!Number.isInteger(n) || n < 0 || n > 6) return null;
  return n <= 2 ? 0 : n <= 4 ? 1 : 2;
}

const ATTENTION = ["held", "failed", "cancelled", "uncertain"];

function fromRows(
  rows: readonly AcquisitionProcessingStageRow[],
  attention: boolean,
): StepState[] {
  const states = PROCESSING_STEPS.map((step): StepState => {
    const state = rows.find((row) => row.stage === step.id)?.state ?? null;
    if (state === "completed" || state === "saved") return "done";
    if (ATTENTION.includes(state ?? "")) return "attention";
    if (state === "running") return attention ? "attention" : "active";
    return "waiting";
  });
  // A later step that has started means the earlier ones are behind it.
  const furthest = states.findLastIndex((state) => state !== "waiting");
  return states.map((state, index) =>
    index < furthest && state === "waiting" ? "done" : state,
  );
}

/**
 * Each step's state. With a plan: earlier steps done, the plan's step active
 * (or needing attention), later ones waiting; a finished plan is all done.
 */
export function projectSteps({
  plan,
  rows,
  attention,
  hasReport,
}: {
  plan: LivePlan | null;
  rows: readonly AcquisitionProcessingStageRow[];
  attention: boolean;
  hasReport: boolean;
}): StepState[] {
  if (hasReport || plan?.reportReady || plan?.state === "completed")
    return PROCESSING_STEPS.map(() => "done");
  const index = stepIndexForStage(plan?.stage ?? null);
  if (index === null) return fromRows(rows, attention);
  const stuck = attention || ATTENTION.includes(plan?.state ?? "");
  return PROCESSING_STEPS.map((_, step) =>
    step < index
      ? "done"
      : step > index
        ? "waiting"
        : stuck
          ? "attention"
          : "active",
  );
}

/** "0:48", "2:05", "1:02:10"; a duration the screen measured itself. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`
    : `${minutes}:${seconds}`;
}

/** The plan as the progress read reports it (newer servers), else null. */
export function livePlanFromProgress(
  progress: Progress | null | undefined,
): LivePlan | null {
  if (!progress || progress.current_stage === undefined) return null;
  return {
    state: progress.run_state === "failed" ? "failed" : progress.state,
    stage: progress.current_stage,
    reportReady: progress.has_report || progress.terminal_state === "done",
  };
}

/** C0–C2 → Listening, C3–C4 → Understanding, C5–C6 → Preparing. */
const STEP_STAGES = [
  ["C0", "C1", "C2"],
  ["C3", "C4"],
  ["C5", "C6"],
] as const;

const times = (rows: readonly StageProgress[], key: keyof StageProgress) =>
  rows
    .map((row) => (row[key] ? Date.parse(row[key] as string) : NaN))
    .filter(Number.isFinite);

/**
 * A step's length by the server's clock: its first recorded start to its
 * last recorded finish. Null unless both were recorded (C0, C3 and C6 never
 * record a start, so a step is timed by the stages that do).
 */
export function serverStepDuration(
  rows: readonly StageProgress[] | undefined,
  step: number,
): number | null {
  const group: readonly string[] = STEP_STAGES[step] ?? [];
  const mine = (rows ?? []).filter((row) => group.includes(row.stage));
  const starts = times(mine, "started_at");
  const ends = times(mine, "finished_at");
  if (!starts.length || !ends.length) return null;
  const length = Math.max(...ends) - Math.min(...starts);
  return length >= 0 ? length : null;
}

/** When the analysis first started by the server's clock, else null. */
export function serverStartedAt(
  rows: readonly StageProgress[] | undefined,
): number | null {
  const starts = times(rows ?? [], "started_at");
  return starts.length ? Math.min(...starts) : null;
}
