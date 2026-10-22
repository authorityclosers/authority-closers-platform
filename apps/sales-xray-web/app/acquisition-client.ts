import { earlyFetch } from "./early-reads";
import {
  callIdFromPath,
  callPath,
  isAppHome,
  NEW_ANALYSIS_PATH,
} from "./analysis-routes";
import { parseCallLabel, type CallLabel } from "./call-label";
import { ReportContractError } from "./report-contract";
import {
  parseLanguageCapabilities,
  type ReportLanguage,
} from "./report-language";

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
  report_languages?: ReportLanguage[];
  report_language_default?: ReportLanguage;
};
export type Allowance = {
  allowance_seconds: number;
  committed_seconds: number;
  available_seconds: number;
  unlimited?: true;
};
export type UploadPolicy = {
  policy_sha256: string;
  title: string;
  description: string;
  privacy_details?: string;
  maximum_file_bytes: number;
  maximum_call_seconds: number;
  retention_days: number;
  // "until_deleted", "keep_for_training" or "days"; absent from older servers.
  retention_mode?: string;
};
export const MAX_ACQUISITION_FILE_BYTES = 100_000_000;
export type Submission = {
  id: string;
  recordingId: string;
  sha: string;
  earlierReportSubmissionId?: string | null;
};
export type LibrarySubmission = {
  id: string;
  createdAt: string;
  durationSeconds: number;
  state: string;
  hasReport: boolean;
  /** Owner call name (C1); null when the server predates labels. */
  label: CallLabel | null;
  /** Returned only when the server authorises organisation rep metadata. */
  owner?: { personId: string; name: string };
  /**
   * The Report's own facts for the row (include_summary=true): null without
   * a readable Report; absent from a server that doesn't send them.
   */
  summary?: RowSummary | null;
  /**
   * The lead this call belongs to (include_leads=true; approved map, slice 7):
   * absent when no lead names the call, or from a server that doesn't send it.
   */
  lead?: CallLead;
};

/** A call's lead: its name and where it stands now (the lead's stage). */
export type CallLead = {
  leadId: string;
  name: string;
  stage: "new" | "not_connected" | "follow_up" | "interested" | "won" | "lost";
  /** The business's own stage, when the seller picked one. */
  step: string | null;
  pipeline: string;
};

const LEAD_STAGES = [
  "new",
  "not_connected",
  "follow_up",
  "interested",
  "won",
  "lost",
] as const;

/** A row's lead, checked: exactly its five fields, or the contract fails. */
export function parseCallLead(value: unknown): CallLead {
  const lead = record(value);
  const short = (field: unknown, max: number) =>
    typeof field === "string" && field.trim().length > 0 && field.length <= max;
  if (
    Object.keys(lead).some(
      (key) => !["lead_id", "name", "stage", "step", "pipeline"].includes(key),
    ) ||
    typeof lead.lead_id !== "string" ||
    !UUID.test(lead.lead_id) ||
    !short(lead.name, 200) ||
    !LEAD_STAGES.includes(lead.stage as CallLead["stage"]) ||
    (lead.step !== null && !short(lead.step, 40)) ||
    !short(lead.pipeline, 40)
  )
    throw new ReportContractError("acquisition_library_lead");
  return {
    leadId: lead.lead_id,
    name: lead.name as string,
    stage: lead.stage as CallLead["stage"],
    step: lead.step as string | null,
    pipeline: lead.pipeline as string,
  };
}

/** A row's Report facts, as the list sends them (include_summary=true). */
export type RowSummary = {
  outcome: string | null;
  assessment: string | null;
  fixFirst: string | null;
  nextFocus: string | null;
  strengths: number | null;
  missed: number | null;
};

const SUMMARY_KEYS = [
  "outcome",
  "assessment",
  "fix_first",
  "next_focus",
  "strengths",
  "missed",
];

/** A row's summary, checked: null, or exactly its six nullable fields. */
export function parseRowSummary(value: unknown): RowSummary | null {
  if (value === null) return null;
  const summary = record(value);
  const text = (key: string) => {
    const field = summary[key];
    if (field === null || field === undefined) return null;
    if (typeof field !== "string" || field.length > 4000)
      throw new ReportContractError("acquisition_library_summary");
    return field;
  };
  const count = (key: string) => {
    const field = summary[key];
    if (field === null || field === undefined) return null;
    if (!Number.isSafeInteger(field) || (field as number) < 0)
      throw new ReportContractError("acquisition_library_summary");
    return field as number;
  };
  if (Object.keys(summary).some((key) => !SUMMARY_KEYS.includes(key)))
    throw new ReportContractError("acquisition_library_summary");
  return {
    outcome: text("outcome"),
    assessment: text("assessment"),
    fixFirst: text("fix_first"),
    nextFocus: text("next_focus"),
    strengths: count("strengths"),
    missed: count("missed"),
  };
}
export type SubmissionLibraryPage = {
  submissions: LibrarySubmission[];
  nextCursor: string | null;
};
export type Progress = {
  state: string;
  local_state: string | null;
  failure_code: string | null;
  has_report: boolean;
  automatic_progression: boolean;
  stages: { stage: string; state: string }[];
  recording_id?: string;
  run_state?: "queued" | "working" | "retrying" | "failed" | "done";
  minute_state?: "reserved" | "released" | "delivered" | null;
  retry_available?: boolean;
  /** The server's own clock for each stage, C0–C6 (Strike C); absent on older servers. */
  stage_progress?: StageProgress[];
  current_stage?: string | null;
  terminal_state?: "done" | "failed" | null;
  /**
   * AI on calls (owner, 21 Oct 2026): the seller's level stopped this call
   * before a paid step (Off, Data only); absent on older servers.
   */
  ai_skip?: AiSkip | null;
};
export type AiSkip = {
  /** The seller's level when the call stopped. */
  level: "off" | "data_only" | "auto" | "full" | null;
  /** Why: the seller's level, or the short-call rule (owner, 21 Oct 2026). */
  reason: "level" | "short_call" | "no_conversation";
  stopped_before: string | null;
  /** The viewer is an organisation owner or admin: "Get full report". */
  can_upgrade: boolean;
};
export type StageProgress = {
  stage: string;
  state: string;
  /** Committed dispatch time; null when no start was recorded. */
  started_at: string | null;
  finished_at: string | null;
};
const STAGE_ID = /^C[0-6]$/;
const instant = (value: unknown) =>
  typeof value === "string" && Number.isFinite(Date.parse(value))
    ? value
    : null;
/** Additive live fields: kept when well formed, dropped (never thrown) otherwise. */
function liveProgress(
  item: Record<string, unknown>,
): Pick<
  Progress,
  "stage_progress" | "current_stage" | "terminal_state" | "ai_skip"
> {
  const live: Pick<
    Progress,
    "stage_progress" | "current_stage" | "terminal_state" | "ai_skip"
  > = {};
  const skip = item.ai_skip;
  if (skip === null) live.ai_skip = null;
  else if (skip && typeof skip === "object" && !Array.isArray(skip)) {
    const row = skip as Record<string, unknown>;
    if (typeof row.can_upgrade === "boolean")
      live.ai_skip = {
        level:
          (["off", "data_only", "auto", "full"] as const).find(
            (level) => level === row.level,
          ) ?? null,
        reason:
          row.reason === "short_call" || row.reason === "no_conversation"
            ? row.reason
            : "level",
        stopped_before:
          typeof row.stopped_before === "string" &&
          STAGE_ID.test(row.stopped_before)
            ? row.stopped_before
            : null,
        can_upgrade: row.can_upgrade,
      };
  }
  const stage = item.current_stage;
  if (stage === null || (typeof stage === "string" && STAGE_ID.test(stage)))
    live.current_stage = stage;
  const terminal = item.terminal_state;
  if (terminal === null || terminal === "done" || terminal === "failed")
    live.terminal_state = terminal;
  if (Array.isArray(item.stage_progress) && item.stage_progress.length <= 7)
    live.stage_progress = item.stage_progress.flatMap((value) => {
      if (!value || typeof value !== "object" || Array.isArray(value))
        return [];
      const row = value as Record<string, unknown>;
      return typeof row.stage === "string" &&
        STAGE_ID.test(row.stage) &&
        typeof row.state === "string"
        ? [
            {
              stage: row.stage,
              state: row.state,
              started_at: instant(row.started_at),
              finished_at: instant(row.finished_at),
            },
          ]
        : [];
    });
  return live;
}

export class AcquisitionError extends Error {
  constructor(
    readonly status: number,
    readonly reason?:
      | "provider_allowance_used"
      | "trial_allowance_insufficient"
      | "plan_permission"
      | "plan_stale"
      | "execution_paused"
      | "source_invalid"
      | "source_incomplete"
      | "source_verification"
      | "source_storage",
    readonly requestId?: string,
  ) {
    const message =
      reason === "source_verification"
        ? "We couldn’t verify this recording’s audio. Try again; if this continues, share the request reference with the AC team."
        : reason === "execution_paused"
          ? ACQUISITION_PAUSED_MESSAGE
          : reason === "source_invalid"
            ? "Choose one bounded audio file and accept the current upload terms."
            : reason === "source_incomplete"
              ? "The complete recording was not received. Check your connection and upload again."
              : reason === "source_storage"
                ? "The recording could not be verified in private storage. Check your connection and upload again."
                : status === 401
                  ? "Your guest session is no longer active. Start a new call with your available allowance, or sign in to recover saved calls."
                  : status === 403
                    ? reason === "trial_allowance_insufficient"
                      ? "This recording is longer than your remaining trial allowance. Contact the AC team for more access."
                      : reason === "provider_allowance_used"
                        ? "This analysis allowance has been used. Your recording is saved. Contact the AC team for help."
                        : reason === "plan_stale"
                          ? "This call’s plan changed while it was being prepared. We fetched a fresh plan for you to review."
                          : reason === "plan_permission"
                            ? "Analysis approval is unavailable for this call. Your recording is saved. Ask the AC team to check its approval and allowance before requesting a fresh plan."
                            : "This action is not available with your current access. Ask the AC team to check your permission."
                    : status === 404
                      ? "This call is unavailable in your current session. It may have expired or been deleted."
                      : status === 429
                        ? "Another call is uploading. Please try again shortly."
                        : status === 409
                          ? "Analysis is not available for this call yet. Your recording remains private; try again shortly."
                          : "This request did not finish. Check your connection and try again.";
    super(requestId ? `${message} Request reference: ${requestId}.` : message);
  }
}
export async function acquisition(
  path: string,
  init: RequestInit = {},
): Promise<unknown> {
  const request: RequestInit = {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", ...init.headers },
  };
  // A plain GET may already be answered by the page's early reads.
  const plain = !init.headers && !init.body && !init.method;
  const response = plain
    ? await earlyFetch(ACQUISITION + path, request)
    : await fetch(ACQUISITION + path, request);
  if (!response.ok) {
    const requestId = response.headers.get("x-request-id") || undefined;
    if (response.status === 503) {
      const body: unknown = await response.json().catch(() => null);
      if (
        body &&
        typeof body === "object" &&
        "detail" in body &&
        body.detail === ACQUISITION_PAUSED_MESSAGE
      )
        throw new AcquisitionError(503, "execution_paused", requestId);
    }
    if (response.status === 403) {
      // Translate only an exact, known denial. Never display server/provider
      // bodies, which can contain private context or infrastructure details.
      const body: unknown = await response.json().catch(() => null);
      const detail =
        body !== null &&
        typeof body === "object" &&
        !Array.isArray(body) &&
        "detail" in body &&
        typeof body.detail === "string"
          ? body.detail
          : undefined;
      if (
        detail ===
        "Your remaining trial minutes are not enough for this recording. Contact AC for more access."
      ) {
        throw new AcquisitionError(
          response.status,
          "trial_allowance_insufficient",
          requestId,
        );
      }
      if (!/^\/submissions\/[0-9a-f-]{36}\/plan(?:\/quote)?$/.test(path))
        throw new AcquisitionError(response.status, undefined, requestId);
      const allowanceUsed =
        detail === "This recording's approved provider allowance is used.";
      const planStale =
        detail === "Approve the current displayed processing plan.";
      throw new AcquisitionError(
        response.status,
        allowanceUsed
          ? "provider_allowance_used"
          : planStale
            ? "plan_stale"
            : "plan_permission",
        requestId,
      );
    }
    if (response.status === 422) {
      const body: unknown = await response.json().catch(() => null);
      const detail =
        body &&
        typeof body === "object" &&
        !Array.isArray(body) &&
        "detail" in body
          ? body.detail
          : undefined;
      const sourceReason =
        detail === "The audio length could not be verified. Try another file."
          ? "source_verification"
          : detail ===
              "Choose an audio or video file up to 100 MB and accept the current upload terms."
            ? "source_invalid"
            : detail === "The complete recording was not received."
              ? "source_incomplete"
              : detail ===
                  "The recording could not be verified in private storage."
                ? "source_storage"
                : undefined;
      throw new AcquisitionError(response.status, sourceReason, requestId);
    }
    throw new AcquisitionError(response.status, undefined, requestId);
  }
  return response.json();
}
export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ReportContractError("acquisition_response");
  return value as Record<string, unknown>;
}
// Standard policies keep recordings up to 7 days; an approved keep-for-training
// policy may keep them (until the owner deletes them) for up to ten years.
export const STANDARD_RETENTION_DAYS = 7;
const MAX_RETENTION_DAYS = 3650;

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
      ...parseLanguageCapabilities(entry),
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
    ...parseLanguageCapabilities(entry),
  };
}
export function parseAllowance(value: unknown): Allowance {
  const item = record(value);
  // A person's balance includes audited admin grants, so it can exceed the
  // advertised trial (the entry's 6,000 s cap still applies there).
  const allowance_seconds = integer(item.allowance_seconds, 2147483647),
    committed_seconds = integer(item.committed_seconds, 2147483647),
    available_seconds = integer(item.available_seconds, 2147483647);
  const unlimited = item.unlimited === true;
  if (
    item.unlimited !== undefined &&
    item.unlimited !== true &&
    item.unlimited !== false
  )
    throw new ReportContractError("acquisition_allowance");
  if (
    !unlimited &&
    available_seconds !== Math.max(0, allowance_seconds - committed_seconds)
  )
    throw new ReportContractError("acquisition_allowance");
  return unlimited
    ? {
        allowance_seconds,
        committed_seconds,
        available_seconds,
        unlimited: true,
      }
    : { allowance_seconds, committed_seconds, available_seconds };
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
    maximum_call_seconds = integer(item.maximum_call_seconds, 7200),
    retention_days = integer(item.retention_days, MAX_RETENTION_DAYS);
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
    ...(typeof item.retention_mode === "string"
      ? { retention_mode: item.retention_mode }
      : {}),
  };
}
export function parseSubmission(value: unknown): Submission {
  const item = record(value),
    earlier = item.earlier_report_submission_id;
  if (
    typeof item.submission_id !== "string" ||
    !UUID.test(item.submission_id) ||
    typeof item.recording_id !== "string" ||
    !UUID.test(item.recording_id) ||
    typeof item.source_sha256 !== "string" ||
    !SHA.test(item.source_sha256) ||
    (earlier !== undefined &&
      earlier !== null &&
      (typeof earlier !== "string" || !UUID.test(earlier)))
  )
    throw new ReportContractError("acquisition_submission");
  return {
    id: item.submission_id,
    recordingId: item.recording_id,
    sha: item.source_sha256,
    earlierReportSubmissionId: typeof earlier === "string" ? earlier : null,
  };
}

export function callHref(id: string, homeHref = "/"): string {
  if (!UUID.test(id)) throw new ReportContractError("submission_id");
  const url = new URL(homeHref, "https://sales-xray.invalid");
  url.searchParams.delete("new");
  url.searchParams.delete("call");
  if (isAppHome(url)) return callPath(id);
  url.searchParams.set("call", id);
  return `${url.pathname}${url.search}${url.hash}`;
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
            "display_name",
            "display_name_revision",
            "owner_person_id",
            "owner_name",
            "summary",
            "lead",
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
    const hasOwner =
      "owner_person_id" in submission || "owner_name" in submission;
    if (
      hasOwner &&
      (typeof submission.owner_person_id !== "string" ||
        !UUID.test(submission.owner_person_id) ||
        typeof submission.owner_name !== "string" ||
        !submission.owner_name.trim())
    )
      throw new ReportContractError("acquisition_library_submission");
    let label: CallLabel | null;
    try {
      label = parseCallLabel(submission);
    } catch {
      throw new ReportContractError("acquisition_library_submission");
    }
    ids.add(submission.submission_id);
    submissions.push({
      id: submission.submission_id,
      createdAt: submission.created_at,
      durationSeconds: submission.duration_seconds as number,
      state: submission.state,
      hasReport: submission.has_report,
      label,
      ...(hasOwner
        ? {
            owner: {
              personId: submission.owner_person_id as string,
              name: submission.owner_name as string,
            },
          }
        : {}),
      ...("summary" in submission
        ? { summary: parseRowSummary(submission.summary) }
        : {}),
      ...("lead" in submission ? { lead: parseCallLead(submission.lead) } : {}),
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
    (item.failure_code !== undefined &&
      item.failure_code !== null &&
      (typeof item.failure_code !== "string" ||
        item.failure_code.length > 128)) ||
    ![null, "queued", "running", "completed", "failed", "cancelled"].includes(
      item.local_state as string | null,
    ) ||
    !Array.isArray(item.stages) ||
    item.stages.length > 128 ||
    (item.run_state !== undefined &&
      (!["queued", "working", "retrying", "failed", "done"].includes(
        item.run_state as string,
      ) ||
        ![null, "reserved", "released", "delivered"].includes(
          item.minute_state as string | null,
        ) ||
        typeof item.retry_available !== "boolean" ||
        item.has_report !== (item.run_state === "done") ||
        (item.retry_available && item.run_state !== "failed")))
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
    failure_code: (item.failure_code as string | null | undefined) ?? null,
    has_report: item.has_report,
    automatic_progression: item.automatic_progression,
    stages,
    ...(item.run_state !== undefined
      ? {
          recording_id: bound.recordingId,
          run_state: item.run_state as Progress["run_state"],
          minute_state: item.minute_state as Progress["minute_state"],
          retry_available: item.retry_available as boolean,
        }
      : {}),
    ...liveProgress(item),
  };
}
export const submissionPath = (id: string) => {
  if (!UUID.test(id)) throw new ReportContractError("submission_id");
  return `/submissions/${id}`;
};

/** How Calls words a lead's stage (New, Not contacted, …), for the Report too. */
export const CALL_LEAD_STAGE_WORDS: Record<CallLead["stage"], string> = {
  new: "New",
  not_connected: "Not contacted",
  follow_up: "Follow up",
  interested: "Interested",
  won: "Won",
  lost: "Lost",
};

/**
 * The call's lead for the Report header (slice 7): the call's own read with the
 * opt-in `include_lead=true`, so the Report never depends on the Calls list's
 * cache. Null when no lead names the call; an older server (422) throws.
 */
export async function readCallLead(
  submissionId: string,
  signal?: AbortSignal,
): Promise<CallLead | null> {
  const body = record(
    await acquisition(`${submissionPath(submissionId)}?include_lead=true`, {
      signal,
    }),
  );
  return body.lead === undefined || body.lead === null
    ? null
    : parseCallLead(body.lead);
}
export function requestedSubmissionId(): string | null {
  const id =
    new URLSearchParams(window.location.search).get("call") ??
    callIdFromPath(window.location.pathname);
  return id && UUID.test(id) ? id : null;
}
export function clearRequestedSubmission() {
  const url = new URL(window.location.href);
  const onCallPath = callIdFromPath(url.pathname) !== null;
  if (!url.searchParams.has("call") && !onCallPath) return;
  url.searchParams.delete("call");
  if (onCallPath) url.pathname = NEW_ANALYSIS_PATH;
  window.history.replaceState(window.history.state, "", url);
}
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
  // A new analysis gets its own address as soon as its call exists, so a
  // reload or a shared link opens that call.
  if (
    id &&
    UUID.test(id) &&
    typeof window !== "undefined" &&
    window.location.pathname === NEW_ANALYSIS_PATH
  )
    window.history.replaceState(window.history.state, "", callPath(id));
}
// An upload whose server outcome is not confirmed yet. It is kept apart from
// the saved-call selector above, so an interrupted upload is reconciled with
// one read instead of being shown as a saved call.
const PENDING_UPLOAD = "ac.xray.pending-upload.v1";
export function pendingUploadId(): string | null {
  try {
    const id = localStorage.getItem(PENDING_UPLOAD);
    return id && UUID.test(id) ? id : null;
  } catch {
    return null;
  }
}
export function rememberPendingUpload(id: string | null) {
  try {
    if (id && UUID.test(id)) localStorage.setItem(PENDING_UPLOAD, id);
    else localStorage.removeItem(PENDING_UPLOAD);
  } catch {
    /* A blocked local store never prevents a private upload. */
  }
}
