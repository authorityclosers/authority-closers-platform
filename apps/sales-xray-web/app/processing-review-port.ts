import type { Progress, Submission } from "./acquisition-client";

export type ProcessingReview = {
  requested: boolean;
  frame: {
    submission: Submission;
    progress: Progress;
    observedAt: number;
  } | null;
  message: string;
};

// Production has no review transport, selectors or retained frame store.
// Only the explicit local webpack development launcher aliases this module.
export function useProcessingReview(_callId: string | null): ProcessingReview {
  void _callId;
  return { requested: false, frame: null, message: "" };
}
