export type JsonRecord = Record<string, unknown>;

export interface PasswordRegistrationInput {
  firstName: string;
  email: string;
  whatsappNumber: string;
  password: string;
  consent: true;
}

export interface PasswordRegistrationResponse {
  status: "verification_required";
}

export interface PasswordSessionResponse {
  authenticated: true;
  person_id: string;
  email: string;
  display_name: string | null;
}

export interface PasswordRecoveryResponse {
  accepted: true;
}

export interface PasswordResetResponse {
  reset: true;
}

export type OnboardingStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "skipped";

export interface OnboardingResponse {
  person_id: string;
  experience_context: string | null;
  learning_goal: string | null;
  practice_situation: string | null;
  weekly_minutes: number | null;
  status: OnboardingStatus;
  current_step: number;
  revision: number;
  updated_at: string;
  next_action_href: string;
  next_action_reason: string;
}

export interface OnboardingSaveInput {
  experienceContext: string | null;
  learningGoal: string | null;
  practiceSituation: string | null;
  weeklyMinutes: number | null;
  status: Exclude<OnboardingStatus, "not_started">;
  currentStep: number;
}

export interface MeResponse {
  person_id: string;
  email: string;
  display_name: string | null;
  email_verified_at: string;
  selected_tenant_id: string | null;
  membership_role: string | null;
  permissions: string[];
}

export interface ContextResponse {
  person_id: string;
  session_id: string;
  tenant_id: string | null;
  membership_role: string | null;
  permissions: string[];
}

export interface ProgramSummaryResponse {
  id: string;
  slug: string;
  title: string;
  program_version_id: string;
  version_number: number;
  published_at: string;
}

export interface ProgramModuleResponse {
  id: string;
  position: number;
  title: string;
  prerequisite_module_ids: string[];
  activities: ProgramActivityResponse[];
}

export interface ProgramActivityResponse {
  id: string;
  position: number;
  kind: string;
  title: string;
  is_required: boolean;
}

export interface ProgramDetailResponse extends ProgramSummaryResponse {
  modules: ProgramModuleResponse[];
}

export interface ProgramCollectionResponse {
  items: ProgramSummaryResponse[];
  next_cursor: string | null;
}

export interface FreeEnrollmentResponse {
  enrollment_id: string;
  entitlement_id: string;
  provenance_id: string;
  created: boolean;
  replayed: boolean;
}

export interface LearningActivityResponse {
  id: string;
  module_id: string;
  program_version_id: string;
  position: number;
  kind: string;
  title: string;
  prompt: string | null;
  state: string;
  revision: number;
  required: boolean;
  explanation: ActivityReasonResponse;
  allowed_actions: ActivityAllowedAction[];
}

export type ActivityAllowedAction =
  | "save_draft"
  | "submit_evidence"
  | "complete_video";

export interface LearningModuleResponse {
  id: string;
  position: number;
  title: string;
  activities: LearningActivityResponse[];
}

export interface ActivityReasonResponse {
  activity_id: string;
  state: string;
  required: boolean;
  reason: string;
  missing_activity_ids: string[];
  missing_module_ids: string[];
}

export interface LearningProjectionResponse {
  scope_type: string;
  scope_id: string;
  program_version: string;
  projection_version: string;
  denominator: number;
  completed_count: number;
  percentage: number;
  predicate: string;
  missing_module_ids: string[];
  activity_reasons: ActivityReasonResponse[];
}

export interface LearningResponse {
  program_id: string;
  program_version_id: string;
  program_slug: string;
  program_title: string;
  version_number: number;
  enrollment_id: string;
  modules: LearningModuleResponse[];
  projection: LearningProjectionResponse;
}

export interface ActivityResponse extends LearningActivityResponse {
  enrollment_id: string;
  draft_revision: number;
  draft_payload: JsonRecord | null;
}

export interface DraftResponse {
  id: string;
  activity_id: string;
  revision: number;
  activity_revision: number;
  status: string;
  payload: JsonRecord;
  saved_at: string;
}

export type EvidenceType =
  | "video_watch"
  | "reflection"
  | "implementation"
  | "review"
  | "improvement";

export interface EvidenceResponse {
  evidence_id: string;
  submission_id: string;
  activity_id: string;
  activity_revision: number;
  evidence_type: string;
  submission_status: string;
}

export interface CertificateResponse {
  id: string;
  certificate_type: "course-completion";
  program_id: string;
  program_version_id: string;
  issued_at: string;
  status: string;
  completion: {
    predicate_version: string;
    required_activity_count: number;
    completed_activity_count: number;
    is_complete: true;
    captured_at: string;
  };
}

export type LearnerFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export type LearnerApiOptions = {
  idempotencyKey?: () => string;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly title: string | null;
  readonly details: JsonRecord | null;

  constructor(
    status: number,
    message: string,
    details: JsonRecord | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = typeof details?.code === "string" ? details.code : null;
    this.title = typeof details?.title === "string" ? details.title : null;
    this.details = details;
  }
}

const defaultIdempotencyKey = (): string => {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `ac-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { title: text };
  }
}

function assertV1Path(path: string): void {
  if (!path.startsWith("/v1/") && path !== "/v1") {
    throw new Error("Learner API requires a same-origin /v1 path.");
  }
  if (path.includes("//") || /^\/v1\/https?:/i.test(path)) {
    throw new Error("Learner API rejects absolute or ambiguous paths.");
  }
}

export function createLearnerApi(
  fetcher: LearnerFetch = globalThis.fetch.bind(globalThis),
  options: LearnerApiOptions = {},
) {
  const makeKey = options.idempotencyKey ?? defaultIdempotencyKey;

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    assertV1Path(path);
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    const response = await fetcher(path, {
      ...init,
      headers,
      credentials: "include",
    });
    const body = await parseBody(response);
    if (!response.ok) {
      const details = isRecord(body) ? body : null;
      const message =
        (details && typeof details.detail === "string" && details.detail) ||
        (details && typeof details.title === "string" && details.title) ||
        `Learner API request failed (${response.status}).`;
      throw new ApiError(response.status, message, details);
    }
    return body as T;
  }

  function jsonMutation<T>(
    path: string,
    body: JsonRecord,
    extraHeaders: Record<string, string> = {},
    method: "POST" | "PUT" = "POST",
  ): Promise<T> {
    return request<T>(path, {
      method,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": makeKey(),
        ...extraHeaders,
      },
      body: JSON.stringify(body),
    });
  }

  return {
    request,
    registerPassword: (input: PasswordRegistrationInput) =>
      jsonMutation<PasswordRegistrationResponse>("/v1/auth/password/register", {
        first_name: input.firstName,
        email: input.email,
        whatsapp_number: input.whatsappNumber,
        password: input.password,
        consent: input.consent,
      }),
    loginPassword: (email: string, password: string) =>
      jsonMutation<PasswordSessionResponse>("/v1/auth/password/login", {
        email,
        password,
      }),
    requestPasswordRecovery: (email: string) =>
      jsonMutation<PasswordRecoveryResponse>("/v1/auth/password/recovery", {
        email,
      }),
    resendPasswordVerification: (email: string) =>
      jsonMutation<PasswordRecoveryResponse>(
        "/v1/auth/password/resend-verification",
        { email },
      ),
    verifyPasswordEmail: (token: string) =>
      jsonMutation<PasswordSessionResponse>("/v1/auth/password/verify", {
        token,
      }),
    resetPassword: (token: string, newPassword: string) =>
      jsonMutation<PasswordResetResponse>("/v1/auth/password/reset", {
        token,
        new_password: newPassword,
      }),
    onboarding: () =>
      request<OnboardingResponse>("/v1/onboarding", { cache: "no-store" }),
    saveOnboarding: (input: OnboardingSaveInput, expectedRevision: number) =>
      jsonMutation<OnboardingResponse>(
        "/v1/onboarding",
        {
          experience_context: input.experienceContext,
          learning_goal: input.learningGoal,
          practice_situation: input.practiceSituation,
          weekly_minutes: input.weeklyMinutes,
          status: input.status,
          current_step: input.currentStep,
        },
        {
          "If-Match": `"onboarding-revision-${expectedRevision}"`,
        },
        "PUT",
      ),
    me: () => request<MeResponse>("/v1/me", { cache: "no-store" }),
    context: () =>
      request<ContextResponse>("/v1/context", { cache: "no-store" }),
    listPrograms: (limit = 50) =>
      request<ProgramCollectionResponse>(`/v1/programs?limit=${limit}`, {
        cache: "no-store",
      }),
    program: (slug: string) =>
      request<ProgramDetailResponse>(
        `/v1/programs/${encodeURIComponent(slug)}`,
        {
          cache: "no-store",
        },
      ),
    enrollFree: (programVersionId: string) =>
      // The browser supplies the Origin header for this same-origin POST;
      // Origin is a forbidden header and must not be forged by app code.
      jsonMutation<FreeEnrollmentResponse>("/v1/enrollments/free", {
        program_version_id: programVersionId,
      }),
    learning: (programId: string) =>
      request<LearningResponse>(
        `/v1/learning/${encodeURIComponent(programId)}`,
        {
          cache: "no-store",
        },
      ),
    activity: (activityId: string) =>
      request<ActivityResponse>(
        `/v1/activities/${encodeURIComponent(activityId)}`,
        {
          cache: "no-store",
        },
      ),
    saveDraft: (activityId: string, payload: JsonRecord, revision: number) =>
      jsonMutation<DraftResponse>(
        `/v1/activities/${encodeURIComponent(activityId)}/draft`,
        { payload },
        { "If-Match": `\"draft-revision-${revision}\"` },
        "PUT",
      ),
    submitEvidence: (
      activityId: string,
      evidenceType: EvidenceType,
      payload: JsonRecord,
      revision: number,
    ) =>
      jsonMutation<EvidenceResponse>(
        `/v1/activities/${encodeURIComponent(activityId)}/evidence`,
        { evidence_type: evidenceType, payload },
        { "If-Match": `\"activity-revision-${revision}\"` },
      ),
    certificate: (certificateId: string) =>
      request<CertificateResponse>(
        `/v1/certificates/${encodeURIComponent(certificateId)}`,
        { cache: "no-store" },
      ),
    logout: () =>
      request<void>("/v1/auth/logout", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
      }),
  };
}

export type LearnerApi = ReturnType<typeof createLearnerApi>;
