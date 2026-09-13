import { ReportContractError } from "./report-contract";

export const ACQUISITION = "/v1/conversation/acquisition";
export const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
export type Entry = {
  enabled: boolean;
  site_key: string | null;
  challenge_action: string | null;
  policy_revision: string | null;
  allowance_seconds: number | null;
};
export type Allowance = {
  allowance_seconds: number;
  committed_seconds: number;
  available_seconds: number;
};
export type UploadPolicy = {
  policy_sha256: string;
  title: string;
  description: string;
  maximum_file_bytes: number;
  maximum_call_seconds: number;
  retention_days: number;
};
export type Submission = { id: string; recordingId: string; sha: string };
export type Progress = {
  state: string;
  local_state: string | null;
  has_report: boolean;
  automatic_progression: boolean;
  stages: { stage: string; state: string }[];
};

export class AcquisitionError extends Error {
  constructor(readonly status: number) {
    super(
      status === 401 || status === 403
        ? "Your session needs attention. Sign in again or return to the browser where you uploaded this call."
        : status === 404
          ? "This call is unavailable in your current session. It may have expired or been deleted."
          : status === 429
            ? "Another call is uploading. Please try again shortly."
            : status === 409
              ? "Analysis is not available for this call yet. Your recording remains private; try again shortly."
              : "This request did not finish. Check your connection and try again.",
    );
  }
}
export async function acquisition(
  path: string,
  init: RequestInit = {},
): Promise<unknown> {
  const response = await fetch(ACQUISITION + path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", ...init.headers },
  });
  if (!response.ok) throw new AcquisitionError(response.status);
  return response.json();
}
export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ReportContractError("acquisition_response");
  return value as Record<string, unknown>;
}
function integer(value: unknown, maximum: number): number {
  if (
    !Number.isSafeInteger(value) ||
    (value as number) < 0 ||
    (value as number) > maximum
  )
    throw new ReportContractError("acquisition_number");
  return value as number;
}
export function parseEntry(value: unknown): Entry {
  const entry = record(value);
  if (entry.enabled === false)
    return {
      enabled: false,
      site_key: null,
      challenge_action: null,
      policy_revision: null,
      allowance_seconds: null,
    };
  if (
    entry.enabled !== true ||
    typeof entry.site_key !== "string" ||
    !/^[A-Za-z0-9_-]{10,128}$/.test(entry.site_key) ||
    typeof entry.challenge_action !== "string" ||
    !/^[A-Za-z0-9_-]{1,32}$/.test(entry.challenge_action) ||
    typeof entry.policy_revision !== "string"
  )
    throw new ReportContractError("acquisition_entry");
  return {
    enabled: true,
    site_key: entry.site_key,
    challenge_action: entry.challenge_action,
    policy_revision: entry.policy_revision,
    allowance_seconds: integer(entry.allowance_seconds, 6000),
  };
}
export function parseAllowance(value: unknown): Allowance {
  const item = record(value);
  const allowance_seconds = integer(item.allowance_seconds, 6000),
    committed_seconds = integer(item.committed_seconds, 2147483647),
    available_seconds = integer(item.available_seconds, 6000);
  if (available_seconds !== Math.max(0, allowance_seconds - committed_seconds))
    throw new ReportContractError("acquisition_allowance");
  return { allowance_seconds, committed_seconds, available_seconds };
}
export function parsePolicy(value: unknown): UploadPolicy {
  const item = record(value);
  if (
    item.schema !== "ac.sales-xray.private-upload-consent/1" ||
    item.max_cost_paise !== 0 ||
    typeof item.policy_sha256 !== "string" ||
    !SHA.test(item.policy_sha256) ||
    typeof item.title !== "string" ||
    typeof item.description !== "string" ||
    item.description.length > 3000
  )
    throw new ReportContractError("acquisition_policy");
  const maximum_file_bytes = integer(item.maximum_file_bytes, 128 * 1024 ** 2),
    maximum_call_seconds = integer(item.maximum_call_seconds, 1800),
    retention_days = integer(item.retention_days, 7);
  if (!maximum_file_bytes || !maximum_call_seconds || !retention_days)
    throw new ReportContractError("acquisition_policy_limit");
  return {
    policy_sha256: item.policy_sha256,
    title: item.title,
    description: item.description,
    maximum_file_bytes,
    maximum_call_seconds,
    retention_days,
  };
}
export function parseSubmission(value: unknown): Submission {
  const item = record(value);
  if (
    typeof item.submission_id !== "string" ||
    !UUID.test(item.submission_id) ||
    typeof item.recording_id !== "string" ||
    !UUID.test(item.recording_id) ||
    typeof item.source_sha256 !== "string" ||
    !SHA.test(item.source_sha256)
  )
    throw new ReportContractError("acquisition_submission");
  return {
    id: item.submission_id,
    recordingId: item.recording_id,
    sha: item.source_sha256,
  };
}
export function parseProgress(
  value: unknown,
  submission: Submission,
): Progress {
  const item = record(value),
    bound = parseSubmission(value);
  if (
    bound.id !== submission.id ||
    bound.recordingId !== submission.recordingId ||
    bound.sha !== submission.sha ||
    typeof item.state !== "string" ||
    typeof item.has_report !== "boolean" ||
    typeof item.automatic_progression !== "boolean" ||
    ![null, "queued", "running", "completed", "failed", "cancelled"].includes(
      item.local_state as string | null,
    ) ||
    !Array.isArray(item.stages) ||
    item.stages.length > 128
  )
    throw new ReportContractError("acquisition_progress");
  const stages = item.stages.map((value) => {
    const stage = record(value);
    if (
      typeof stage.stage !== "string" ||
      !["C2", "C4", "C5"].includes(stage.stage) ||
      typeof stage.state !== "string"
    )
      throw new ReportContractError("acquisition_stage");
    return { stage: stage.stage, state: stage.state };
  });
  return {
    state: item.state,
    local_state: item.local_state as string | null,
    has_report: item.has_report,
    automatic_progression: item.automatic_progression,
    stages,
  };
}
export const submissionPath = (id: string) => {
  if (!UUID.test(id)) throw new ReportContractError("submission_id");
  return `/submissions/${id}`;
};
export function savedSubmissionId(): string | null {
  try {
    const id = localStorage.getItem("ac.xray.submission.v1");
    return id && UUID.test(id) ? id : null;
  } catch {
    return null;
  }
}
export function rememberSubmission(id: string | null) {
  try {
    if (id && UUID.test(id)) localStorage.setItem("ac.xray.submission.v1", id);
    else localStorage.removeItem("ac.xray.submission.v1");
  } catch {
    /* A blocked local store never prevents a private upload. */
  }
}
