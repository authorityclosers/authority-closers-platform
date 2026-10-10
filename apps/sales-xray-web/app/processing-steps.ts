/**
 * The three steps a call moves through while it is analysed. The processing
 * plan's current stage (C0–C6) is the live truth; the submission's task rows
 * (C2, C4, C5) are the fallback when a server has no plan for the call.
 * Nothing here advances on a timer.
 */
import type { AcquisitionProcessingStageRow } from "./acquisition-processing-panel";

export const PROCESSING_STEPS = [
  {
    id: "C2",
    title: "Listening",
    description: "Transcribing and separating the speakers",
  },
  {
    id: "C4",
    title: "Understanding",
    description: "Finding key moments, objections and next steps",
  },
  {
    id: "C5",
    title: "Preparing your report",
    description: "Turning the findings into your report",
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
