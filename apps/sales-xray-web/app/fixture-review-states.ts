import type { Progress, Submission } from "./acquisition-client";
import type {
  LocalReviewObservation,
  ReviewNavigation,
} from "./processing-review-port";

// This catalogue is imported only by the explicit local development review port.
// It contains no report, source audio, accepted consent, or provider operation.
export const fixtureStateIds = [
  "auth.email",
  "auth.code",
  "auth.error",
  "profile.required",
  "profile.unverified",
  "profile.ready",
  "upload.empty",
  "upload.selected",
  "upload.validation",
  "processing.received",
  "processing.transcribing",
  "processing.conversation",
  "processing.report",
  "processing.paused",
  "processing.failed",
] as const;

export type FixtureStateId = (typeof fixtureStateIds)[number];
export type FixtureReviewFrame = {
  id: FixtureStateId;
  label: string;
  kind: "auth" | "profile" | "upload" | "processing";
  observation: LocalReviewObservation | null;
  submission: Submission | null;
  progress: Progress | null;
  navigation: ReviewNavigation;
};

const labels: Record<FixtureStateId, string> = {
  "auth.email": "Sign in with email",
  "auth.code": "Enter email code",
  "auth.error": "Email verification error",
  "profile.required": "Complete your profile",
  "profile.unverified": "Verify mobile number",
  "profile.ready": "Profile ready",
  "upload.empty": "Empty upload",
  "upload.selected": "Selected audio",
  "upload.validation": "Invalid replacement",
  "processing.received": "Recording received",
  "processing.transcribing": "Transcribing",
  "processing.conversation": "Checking conversation",
  "processing.report": "Writing report",
  "processing.paused": "Analysis paused",
  "processing.failed": "Analysis needs attention",
};

const syntheticSubmission: Submission = {
  id: "00000000-0000-4000-8000-000000000001",
  recordingId: "00000000-0000-4000-8000-000000000002",
  sha: "0".repeat(64),
};

function uploadObservation(id: FixtureStateId): LocalReviewObservation | null {
  if (!id.startsWith("upload.")) return null;
  const selected = id !== "upload.empty";
  return {
    phase:
      id === "upload.validation"
        ? "upload.validation.error"
        : selected
          ? "upload.file.selected"
          : "upload.empty",
    privacy_open: selected,
    consent_checked: false,
    report_language: "en",
    verification: "checking",
    file_name: selected ? "Example call.wav" : null,
    file_size_bytes: selected ? 1_048_576 : null,
  };
}

function processingProgress(id: FixtureStateId): Progress | null {
  if (!id.startsWith("processing.")) return null;
  const received = id === "processing.received";
  const transcribing = id === "processing.transcribing";
  const conversation = id === "processing.conversation";
  const report = id === "processing.report";
  const paused = id === "processing.paused";
  const failed = id === "processing.failed";
  return {
    state: paused ? "held" : failed ? "failed" : "active",
    local_state: "completed",
    failure_code: null,
    has_report: false,
    automatic_progression: true,
    stages: received
      ? []
      : transcribing
        ? [{ stage: "C2", state: "running" }]
        : conversation
          ? [
              { stage: "C2", state: "completed" },
              { stage: "C4", state: "running" },
            ]
          : report
            ? [
                { stage: "C2", state: "completed" },
                { stage: "C4", state: "completed" },
                { stage: "C5", state: "running" },
              ]
            : [
                { stage: "C2", state: "completed" },
                { stage: "C4", state: paused ? "uncertain" : "failed" },
              ],
  };
}

export function fixtureStateId(search: string): FixtureStateId | null {
  const params = new URLSearchParams(search);
  if (
    params.getAll("new").length !== 1 ||
    params.get("new") !== "1" ||
    params.getAll("sx-fixture").length !== 1 ||
    [...params.keys()].some((key) => !["new", "sx-fixture"].includes(key))
  )
    return null;
  const id = params.get("sx-fixture");
  return fixtureStateIds.find((candidate) => candidate === id) ?? null;
}

export function fixtureUrl(id: FixtureStateId): string {
  return `/?new=1&sx-fixture=${encodeURIComponent(id)}`;
}

export function fixtureFrame(id: FixtureStateId): FixtureReviewFrame {
  const index = fixtureStateIds.indexOf(id);
  const progress = processingProgress(id);
  return {
    id,
    label: labels[id],
    kind: id.startsWith("auth.")
      ? "auth"
      : id.startsWith("profile.")
        ? "profile"
        : progress
          ? "processing"
          : "upload",
    observation: uploadObservation(id),
    submission: progress ? syntheticSubmission : null,
    progress,
    navigation: {
      previousUrl: index > 0 ? fixtureUrl(fixtureStateIds[index - 1]) : null,
      nextUrl:
        index + 1 < fixtureStateIds.length
          ? fixtureUrl(fixtureStateIds[index + 1])
          : null,
      position: index + 1,
      total: fixtureStateIds.length,
    },
  };
}
