export const ACTIVITY_KINDS = [
  "VIDEO",
  "REFLECTION",
  "IMPLEMENTATION_CHALLENGE",
  "REVIEW",
  "IMPROVE",
] as const;

export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

export const ACTIVITY_STATUSES = [
  "LOCKED",
  "PREVIEW",
  "AVAILABLE",
  "IN_PROGRESS",
  "AWAITING_REVIEW",
  "COMPLETED",
] as const;

export type ActivityStatus = (typeof ACTIVITY_STATUSES)[number];

export interface ActivityViewModel {
  id: string;
  order: number;
  title: string;
  eyebrow: string;
  kind: ActivityKind;
  status: ActivityStatus;
  duration: string;
  objective: string;
  prompt: string;
  evidenceLabel: string;
  helperText: string;
}

export interface ModuleViewModel {
  id: string;
  number: string;
  title: string;
  summary: string;
  prerequisite: string;
  status: "AVAILABLE" | "LOCKED" | "COMPLETED";
  activities: ActivityViewModel[];
}

/**
 * Local, read-only content shape for the first UI slice.
 * A future API adapter can return this same view model without making the UI
 * authoritative for enrollment, progression, evidence, or certificate state.
 */
export interface ProgramViewModel {
  slug: string;
  title: string;
  eyebrow: string;
  shortDescription: string;
  description: string;
  previewLabel: string;
  formatLabel: string;
  learningLoop: string[];
  modules: ModuleViewModel[];
}

export interface LearnerViewModel {
  displayName: string;
  initials: string;
  workspaceLabel: string;
  currentProgramSlug: string;
  previewProgressLabel: string;
  nextActivityId: string;
  draftSeamLabel: string;
}

export interface CertificateViewModel {
  id: string;
  learnerName: string;
  programTitle: string;
  issuedLabel: string;
  certificateStatus: "PREVIEW_NOT_ISSUED";
  distinction: string;
}
