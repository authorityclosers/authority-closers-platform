import type { Progress, Submission } from "./acquisition-client";

export type ProcessingReview = {
  requested: boolean;
  frame: {
    submission: Submission;
    progress: Progress;
    observedAt: number;
    navigation: ReviewNavigation | null;
  } | null;
  localRequested: boolean;
  localFrame: {
    id: string;
    observedAt: number;
    expiresAt: number;
    label: string;
    observation: LocalReviewObservation;
    navigation: ReviewNavigation | null;
  } | null;
  readOnly: boolean | null;
  captureLocal: (observation: LocalReviewObservation) => void;
  message: string;
};

export type ReviewNavigation = {
  previousUrl: string | null;
  nextUrl: string | null;
  position: number;
  total: number;
};

export type LocalReviewObservation = {
  phase: "upload.empty" | "upload.file.selected" | "upload.validation.error";
  privacy_open: boolean;
  consent_checked: boolean;
  report_language: "en" | "hi-Deva+en" | "mr-Deva+en" | null;
  verification:
    | "checking"
    | "session-present"
    | "guest-challenge-required"
    | "guest-challenge-complete";
  file_name: string | null;
  file_size_bytes: number | null;
};

const noopCaptureLocal = (_observation: LocalReviewObservation) => {
  void _observation;
};

// Production has no review transport, selectors or retained frame store.
// Only the explicit local webpack development launcher aliases this module.
export function useProcessingReview(_callId: string | null): ProcessingReview {
  void _callId;
  return {
    requested: false,
    frame: null,
    localRequested: false,
    localFrame: null,
    readOnly: false,
    captureLocal: noopCaptureLocal,
    message: "",
  };
}
