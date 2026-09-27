import type { Progress } from "./acquisition-client";

export const processingStages = ["C2", "C4", "C5"] as const;
export type ProcessingStage = (typeof processingStages)[number];
export const stageNames = {
  C2: "Transcribing your call",
  C4: "Checking the conversation",
  C5: "Writing your coaching report",
};
export const stageLabels = {
  C2: "Transcript",
  C4: "Conversation",
  C5: "Report",
};
export function latestStage(progress: Progress | null, stage: ProcessingStage) {
  return progress?.stages.findLast((row) => row.stage === stage) ?? null;
}
export function stageStatusLabel(status: string | null) {
  if (status === "completed") return "Complete";
  if (status === "saved") return "Work saved";
  if (status === "running") return "In progress";
  if (status === "uncertain") return "Paused · needs attention";
  if (status === "queued" || status === "pending") return "Queued";
  if (status === "cancelled") return "Cancelled";
  if (status === "failed" || status === "held") return "Needs attention";
  return status === null ? "Not started" : "Status needs checking";
}

/** No clock, percentage, or client connection signal can advance these facts. */
export function projectProcessing(
  progress: Progress | null,
  waitingForApproval: boolean,
) {
  const rows = processingStages.map((stage) => {
    const latest = latestStage(progress, stage);
    const state =
      latest?.state === "completed" &&
      stage === "C4" &&
      !latestStage(progress, "C5")
        ? "saved"
        : (latest?.state ?? null);
    return { stage, state, label: stageStatusLabel(state) };
  });
  const paused =
    progress?.state === "held" || rows.some((row) => row.state === "uncertain");
  const attention = Boolean(
    paused ||
      ["failed", "cancelled"].includes(progress?.local_state ?? "") ||
      ["failed", "cancelled", "completed"].includes(progress?.state ?? "") ||
      rows.some((row) =>
        ["failed", "held", "cancelled"].includes(row.state ?? ""),
      ),
  );
  const current =
    rows.findLast((row) => row.state === "running") ??
    rows.find((row) => row.state === "queued" || row.state === "pending");
  const known = [
    "pending",
    "queued",
    "running",
    "completed",
    "active",
    "ready",
    "received",
    "saved",
    "held",
    "failed",
    "cancelled",
    "uncertain",
  ];
  const unknown =
    rows.some((row) => row.state !== null && !known.includes(row.state)) ||
    (progress !== null &&
      (!known.includes(progress.state) ||
        (progress.local_state !== null &&
          !known.includes(progress.local_state))));
  const title = progress?.has_report
    ? "Opening your report"
    : paused
      ? "Analysis paused"
      : attention
        ? "Your call needs attention"
        : unknown
          ? "Checking analysis status"
          : waitingForApproval
            ? "Ready to start"
            : progress?.local_state !== "completed"
              ? "Checking your recording"
              : current
                ? current.state === "running"
                  ? stageNames[current.stage]
                  : `Waiting to start ${stageLabels[current.stage].toLowerCase()}`
                : "Waiting for the next stage";
  return {
    rows,
    paused: Boolean(paused),
    attention: attention && !progress?.has_report,
    current,
    title,
    unknown,
    savedTranscript:
      progress?.stages.some(
        (row) => row.stage === "C2" && row.state === "completed",
      ) ?? false,
    savedEvidence:
      progress?.stages.some(
        (row) => row.stage === "C4" && row.state === "completed",
      ) ?? false,
  };
}
