import { ReportContractError } from "./report-contract";

export const ACQUISITION = "/v1/conversation/acquisition";
export const ACQUISITION_PAUSED_MESSAGE =
  "New analysis is temporarily paused. Your saved calls and reports are still available. Contact the AC team at admin@authorityclosers.com.";
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
  privacy_details?: string;
  maximum_file_bytes: number;
  maximum_call_seconds: number;
  retention_days: number;
};
export const MAX_ACQUISITION_FILE_BYTES = 32 * 1024 ** 2;
export type Submission = { id: string; recordingId: string; sha: string };
export type LibrarySubmission = {
  id: string;
  createdAt: string;
  durationSeconds: number;
  state: string;
  hasReport: boolean;
};
export type SubmissionLibraryPage = {
  submissions: LibrarySubmission[];
  nextCursor: string | null;
};
export type Progress = {
  state: string;
  local_state: string | null;
  has_report: boolean;
  automatic_progression: boolean;
  stages: { stage: string; state: string }[];
};

export class AcquisitionError extends Error {
  constructor(
    readonly status: number,
    reason?: "provider_allowance_used" | "plan_permission" | "execution_paused",
  ) {
    super(
      reason === "execution_paused"
        ? ACQUISITION_PAUSED_MESSAGE
        : status === 401
          ? "Your session needs attention. Sign in again or return to the browser where you uploaded this call."
          : status === 403
            ? reason === "provider_allowance_used"
              ? "This call’s approved analysis allowance has been used. Your recording is saved. Ask the AC team to review its approval before requesting a fresh plan."
              : reason === "plan_permission"
                ? "Analysis approval is unavailable for this call. Your recording is saved. Ask the AC team to check its approval and allowance before requesting a fresh plan."
                : "This action is not available with your current access. Ask the AC team to check your permission."
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
  if (!response.ok) {
    if (response.status === 503) {
      const body: unknown = await response.json().catch(() => null);
      if (
        body &&
        typeof body === "object" &&
        "detail" in body &&
        body.detail === ACQUISITION_PAUSED_MESSAGE
      )
        throw new AcquisitionError(503, "execution_paused");
    }
    if (
      response.status === 403 &&
      /^\/submissions\/[0-9a-f-]{36}\/plan(?:\/quote)?$/.test(path)
    ) {
      // Translate only an exact, known denial. Never display server/provider
      // bodies, which can contain private context or infrastructure details.
      const body: unknown = await response.json().catch(() => null);
      const allowanceUsed =
        body !== null &&
        typeof body === "object" &&
        !Array.isArray(body) &&
        "detail" in body &&
        body.detail === "This recording's approved provider allowance is used.";
      throw new AcquisitionError(
        response.status,
        allowanceUsed ? "provider_allowance_used" : "plan_permission",
      );
    }
    throw new AcquisitionError(response.status);
  }
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
  // The authenticated learner entry uses the existing Academy session; the
  // server deliberately omits guest challenge credentials on that host.
  if (entry.auth_mode === "account") {
    if (
      entry.enabled !== true ||
      entry.site_key !== null ||
      entry.challenge_action !== null ||
      typeof entry.policy_revision !== "string"
    )
      throw new ReportContractError("acquisition_entry");
    return {
      enabled: true,
      site_key: null,
      challenge_action: null,
      policy_revision: entry.policy_revision,
      allowance_seconds: integer(entry.allowance_seconds, 6000),
    };
  }
  if (
    entry.enabled !== true ||
    entry.auth_mode !== undefined ||
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
  const maximum_file_bytes = integer(
      item.maximum_file_bytes,
      MAX_ACQUISITION_FILE_BYTES,
    ),
    maximum_call_seconds = integer(item.maximum_call_seconds, 1800),
    retention_days = integer(item.retention_days, 7);
  const privacy_details =
    typeof item.privacy_details === "string"
      ? item.privacy_details
      : Array.isArray(item.privacy_details)
        ? item.privacy_details
            .filter((value): value is string => typeof value === "string")
            .join(" ")
        : "";
  if (
    !maximum_file_bytes ||
    maximum_file_bytes > MAX_ACQUISITION_FILE_BYTES ||
    !maximum_call_seconds ||
    !retention_days
  )
    throw new ReportContractError("acquisition_policy_limit");
  return {
    policy_sha256: item.policy_sha256,
    title: item.title,
    description: item.description,
    privacy_details,
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

function iso8601(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(
      value,
    )
  )
    return false;
  return Number.isFinite(Date.parse(value));
}

export function parseSubmissionLibraryPage(
  value: unknown,
): SubmissionLibraryPage {
  const item = record(value);
  if (
    Object.keys(item).some(
      (key) => !["submissions", "next_cursor"].includes(key),
    ) ||
    !Array.isArray(item.submissions) ||
    item.submissions.length > 20 ||
    (item.next_cursor !== null &&
      (typeof item.next_cursor !== "string" || !UUID.test(item.next_cursor)))
  )
    throw new ReportContractError("acquisition_library");

  const ids = new Set<string>();
  const submissions: LibrarySubmission[] = [];
  for (const value of item.submissions) {
    const submission = record(value);
    if (
      Object.keys(submission).some(
        (key) =>
          ![
            "submission_id",
            "created_at",
            "duration_seconds",
            "state",
            "has_report",
          ].includes(key),
      ) ||
      typeof submission.submission_id !== "string" ||
      !UUID.test(submission.submission_id) ||
      ids.has(submission.submission_id) ||
      !iso8601(submission.created_at) ||
      !Number.isSafeInteger(submission.duration_seconds) ||
      (submission.duration_seconds as number) <= 0 ||
      typeof submission.state !== "string" ||
      submission.state.length === 0 ||
      submission.state.length > 128 ||
      typeof submission.has_report !== "boolean"
    )
      throw new ReportContractError("acquisition_library_submission");
    ids.add(submission.submission_id);
    submissions.push({
      id: submission.submission_id,
      createdAt: submission.created_at,
      durationSeconds: submission.duration_seconds as number,
      state: submission.state,
      hasReport: submission.has_report,
    });
  }
  return {
    submissions,
    nextCursor: item.next_cursor as string | null,
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
