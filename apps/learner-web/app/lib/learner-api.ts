import {
  getDefaultOfflineReadCache,
  getOfflineReadPolicy,
  markOfflineRead,
  type OfflineReadCache,
  type OfflineReadCacheLease,
} from "./offline-read-cache";

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
  /** Optional until the server-owned profile object contract is activated. */
  avatar?: {
    deliveryUrl: string;
    alt: string;
    revision: string;
  } | null;
  profile_revision?: string | number | null;
  email_verified_at: string;
  selected_tenant_id: string | null;
  membership_role: string | null;
  permissions: string[];
}

export interface CommunityProfileResponse {
  username: string | null;
  leaderboard_opted_in: boolean;
  revision: number;
  leaderboard_policy: {
    version: "all_time_practice_xp_v1";
    period: "all_time";
    measure: "confirmed_practice_xp";
    ranking: "competition";
    privacy: "academy_opt_in";
  };
}

export interface CommunityLeaderboardResponse {
  policy: {
    version: "all_time_practice_xp_v1";
    label: "All-time practice XP";
    period: "all_time";
    ranking: "competition";
    scope: "academy";
  };
  items: Array<{
    rank: number;
    username: string;
    xp_total: number;
    is_current_learner: boolean;
  }>;
  next_cursor: string | null;
}

export interface AvatarCropMetadata {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: number;
}

export type MediaLifecycle =
  | "expected"
  | "uploading"
  | "processing"
  | "ready"
  | "failed"
  | "retired";

export interface ProfileAvatarVersionResponse {
  asset_id: string;
  version_id: string;
  version_number: number;
  state: MediaLifecycle;
  delivery_url: string | null;
  content_type: string;
  size_px: number | null;
  avatar_crop: AvatarCropMetadata | null;
  supersedes_version_id: string | null;
  updated_at: string;
}

export interface ProfileAvatarResponse {
  avatar: ProfileAvatarVersionResponse | null;
  pending: ProfileAvatarVersionResponse | null;
}

export interface AvatarUploadIntentResponse {
  upload_id: string;
  media_id: string;
  media_version_id: string;
  version_number: number;
  state: MediaLifecycle;
  object_key: string;
  upload_url: string;
  upload_headers: Record<string, string>;
  expires_at: string;
  max_bytes: number;
}

export interface MediaAssetResponse {
  id: string;
  tenant_id: string;
  owner_person_id: string;
  purpose: string;
  state: MediaLifecycle;
  current_version_id: string | null;
  current_version: {
    id: string;
    asset_id: string;
    version_number: number;
    state: MediaLifecycle;
    content_type: string;
    avatar_crop: AvatarCropMetadata | null;
  } | null;
  version_count: number;
}

export interface ProfileAvatarUploadInput {
  filename: string;
  content_type: string;
  content_length: number;
  checksum_sha256: string;
  asset_id?: string | null;
  supersedes_version_id?: string | null;
  crop?: AvatarCropMetadata | null;
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

export type PlanningPeriod = "today" | "week" | "month";

export interface LearningPlanItemResponse {
  id: string;
  tenant_id: string;
  person_id: string;
  period: PlanningPeriod;
  title: string;
  activity_id: string | null;
  planned_for: string | null;
  state: "planned" | "completed";
  source: "explicit_learning_plan";
}

export interface LearningPlanResponse {
  period: PlanningPeriod;
  status: "not_configured" | "available";
  source: "explicit_learning_plan";
  items: LearningPlanItemResponse[];
  message: string | null;
}

export interface CalendarResponse {
  source: "explicit_learning_plan";
  periods: Record<PlanningPeriod, LearningPlanResponse>;
  disclaimer: string;
}

/**
 * A descriptive read model. This is deliberately kept separate from the
 * canonical learning projection above: analytics can be unavailable or
 * stale without changing course completion, access, or payment state.
 */
export type AnalyticsStatus = "insufficient_signal" | "available";

export interface LearningInsightResponse {
  id: string;
  kind: "descriptive_signal";
  title: string;
  detail: string;
  observed_event_count: number;
  source_event_names: string[];
}

export interface AnalyticsViewResponse {
  status: AnalyticsStatus;
  source: "descriptive_analytics_projection";
  period: PlanningPeriod | null;
  freshness_as_of: string | null;
  retained_event_count: number;
  insights: LearningInsightResponse[];
  disclaimer: string;
}

export type LearningCourseState = "in_progress" | "completed" | "unavailable";

export type LearningSavedState = "saved" | "unavailable";

export interface LearningCourseSummaryResponse {
  program_id: string;
  program_version_id: string;
  program_slug: string;
  program_title: string;
  version_number: number;
  enrollment_id: string;
  enrolled_at: string;
  updated_at: string;
  state: LearningCourseState;
  saved_state: LearningSavedState;
  projection: LearningProjectionResponse | null;
}

export interface LearningCollectionResponse {
  items: LearningCourseSummaryResponse[];
  next_cursor: string | null;
  saved_filter_available: boolean;
}

export interface ActivityResponse extends LearningActivityResponse {
  program_id: string;
  enrollment_id: string;
  draft_revision: number;
  draft_payload: JsonRecord | null;
  media?: ActivityMediaDescriptor | null;
}

export interface ActivityMediaDescriptor {
  state: "approved" | "blocked" | "unavailable";
  reason: string;
  binding_id: string | null;
  media_id: string | null;
  media_version_id: string | null;
  activity_version: string | null;
  content_type: string | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  renditions: Array<{
    id: string;
    protocol: "hls" | "progressive";
    content_type: string;
    width: number | null;
    height: number | null;
    bitrate_kbps: number | null;
  }>;
  captions: Array<{
    id: string;
    media_version_id: string;
    language: string;
    kind: "captions" | "subtitles" | "transcript";
    state: "ready" | "superseded" | "retired";
    content_type: string;
    is_default: boolean;
    source_url?: string | null;
    supersedes_caption_id?: string | null;
    created_at: string;
  }>;
  delivery: {
    protocol: "hls" | "progressive";
    manifest_url: string | null;
    progressive_url: string | null;
  } | null;
  playback_available: boolean;
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

export interface PlaybackStartResponse {
  session_id: string;
  activity_id: string;
  session_token: string;
  revision: number;
  expires_at: string;
  duration_seconds: number;
}

export interface PlaybackEventInput {
  session_id: string;
  event_id: string;
  sequence: number;
  start_seconds: number;
  end_seconds: number;
  kind: "watch" | "seek";
}

export interface PlaybackEventResponse {
  session_id: string;
  interval_id: string;
  sequence: number;
  revision: number;
  observed_at: string;
}

export interface PlaybackFinishResponse {
  session_id: string;
  activity_id: string;
  revision: number;
  status: string;
  closed_at: string | null;
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

export type LearnerReadOptions = Pick<RequestInit, "signal">;

export type LearningCollectionReadOptions = LearnerReadOptions & {
  cursor?: string;
};

export type LearnerApiOptions = {
  idempotencyKey?: () => string;
  offlineReadCache?: OfflineReadCache | null;
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

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

const defaultIdempotencyKey = (): string => {
  const runtimeCrypto = globalThis.crypto as
    | (Pick<Crypto, "getRandomValues"> & { randomUUID?: () => string })
    | undefined;
  if (typeof runtimeCrypto?.randomUUID === "function") {
    return runtimeCrypto.randomUUID();
  }
  if (runtimeCrypto) {
    const bytes = runtimeCrypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (value: number) =>
      value.toString(16).padStart(2, "0"),
    ).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  throw new Error(
    "Secure random idempotency keys are unavailable in this browser.",
  );
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
  const offlineReadCache =
    options.offlineReadCache === undefined
      ? getDefaultOfflineReadCache()
      : options.offlineReadCache;
  const pendingOperationKeys = new Map<
    string,
    { fingerprint: string; key: string }
  >();
  const inFlightGetRequests = new Map<string, Promise<unknown>>();
  // Every private offline write carries this cache-issued lease. The cache,
  // not this API instance, decides whether its owner generation is current.
  let ownerLease: OfflineReadCacheLease | null = null;

  function getGetDedupeKey(path: string, init: RequestInit): string | null {
    // A request with a caller-owned signal must remain independently
    // cancellable. It is therefore intentionally not deduplicated.
    if (init.signal || init.body !== undefined) return null;

    const headers = Array.from(new Headers(init.headers).entries()).sort(
      ([left], [right]) => left.localeCompare(right),
    );
    return JSON.stringify([
      path,
      headers,
      init.cache ?? "default",
      "include",
      init.mode ?? "cors",
      init.redirect ?? "follow",
      init.referrer ?? "",
      init.referrerPolicy ?? "",
      init.integrity ?? "",
      init.keepalive ?? false,
    ]);
  }

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    assertV1Path(path);
    const method = (init.method || "GET").toUpperCase();
    const offlinePolicy = getOfflineReadPolicy(path, method);
    // Capture the cache-owned lease before any asynchronous work starts. A
    // later identity response, logout, or concurrent API request may update
    // the mutable ownerLease, but it must never retag this response.
    const capturedOwnerLease = offlinePolicy?.requiresOwner ? ownerLease : null;
    let identityWriteLease: OfflineReadCacheLease | null = null;
    const dedupeKey = method === "GET" ? getGetDedupeKey(path, init) : null;
    if (method === "GET") {
      const active = dedupeKey ? inFlightGetRequests.get(dedupeKey) : undefined;
      if (active) {
        return active as Promise<T>;
      }
    }

    const execution = (async () => {
      try {
        const headers = new Headers(init.headers);
        headers.set("Accept", "application/json");
        try {
          const response = await fetcher(path, {
            ...init,
            headers,
            credentials: "include",
          });
          const body = await parseBody(response);
          if (!response.ok) {
            const details = isRecord(body) ? body : null;
            const message =
              (details &&
                typeof details.detail === "string" &&
                details.detail) ||
              (details && typeof details.title === "string" && details.title) ||
              `Learner API request failed (${response.status}).`;
            if (response.status === 401 || response.status === 403) {
              ownerLease = null;
              try {
                await offlineReadCache?.purge();
              } catch {
                // The canonical authentication/authorization error still wins.
              }
            }
            throw new ApiError(response.status, message, details);
          }

          if (
            method === "GET" &&
            (path === "/v1/me" || path === "/v1/context")
          ) {
            ownerLease = null;
            identityWriteLease = null;
            if (isRecord(body) && typeof body.person_id === "string") {
              try {
                const tenantId =
                  path === "/v1/me"
                    ? typeof body.selected_tenant_id === "string"
                      ? body.selected_tenant_id
                      : null
                    : typeof body.tenant_id === "string"
                      ? body.tenant_id
                      : null;
                const activation = await offlineReadCache?.activateOwner(
                  body.person_id,
                  tenantId,
                );
                identityWriteLease = activation?.ok ? activation.lease : null;
                ownerLease = identityWriteLease;
              } catch {
                // Online identity/context reads remain available, but a
                // failed durable owner binding must not issue a private lease.
                ownerLease = null;
              }
            }
          }
          const writeLease =
            path === "/v1/me" ? identityWriteLease : capturedOwnerLease;
          if (
            method === "GET" &&
            offlinePolicy &&
            (!offlinePolicy.requiresOwner || writeLease !== null)
          ) {
            const write = offlinePolicy.requiresOwner
              ? offlineReadCache?.put(
                  path,
                  body,
                  writeLease as OfflineReadCacheLease,
                )
              : offlineReadCache?.put(path, body);
            void write?.catch(() => undefined);
          }
          return body as T;
        } catch (error) {
          // Fetch and response-body network failures both surface as TypeError
          // in browsers. Keep the fallback narrow so API errors, aborts, and
          // protected mutations can never be replaced by stale data.
          const canUseOfflineFallback =
            method === "GET" &&
            error instanceof TypeError &&
            !isAbortError(error) &&
            !init.signal?.aborted &&
            getOfflineReadPolicy(path, method) !== null;
          if (canUseOfflineFallback && offlineReadCache) {
            try {
              const cached = await offlineReadCache.get(path);
              if (cached && !init.signal?.aborted) {
                return markOfflineRead(cached.data, cached.savedAt) as T;
              }
            } catch {
              // Cache recovery is best-effort. Preserve the original network
              // failure and its honest UI state when recovery is unavailable.
            }
          }
          throw error;
        }
      } finally {
        if (dedupeKey) {
          inFlightGetRequests.delete(dedupeKey);
        }
      }
    })();

    if (dedupeKey && execution) {
      inFlightGetRequests.set(dedupeKey, execution);
    }

    return execution;
  }

  function jsonMutation<T>(
    path: string,
    body: JsonRecord,
    extraHeaders: Record<string, string> = {},
    method: "POST" | "PUT" = "POST",
    idempotencyKey = makeKey(),
    signal?: AbortSignal,
  ): Promise<T> {
    return request<T>(path, {
      method,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        ...extraHeaders,
      },
      body: JSON.stringify(body),
      signal,
    });
  }

  function stableFingerprint(value: unknown): string {
    if (Array.isArray(value)) {
      return `[${value.map(stableFingerprint).join(",")}]`;
    }
    if (isRecord(value)) {
      return `{${Object.keys(value)
        .sort()
        .map((key) => `${JSON.stringify(key)}:${stableFingerprint(value[key])}`)
        .join(",")}}`;
    }
    return JSON.stringify(value) ?? "undefined";
  }

  async function logicalJsonMutation<T>(
    operationScope: string,
    path: string,
    body: JsonRecord,
    extraHeaders: Record<string, string> = {},
    method: "POST" | "PUT" = "POST",
    signal?: AbortSignal,
  ): Promise<T> {
    const fingerprint = stableFingerprint({ body, extraHeaders, method, path });
    const pending = pendingOperationKeys.get(operationScope);
    const key = pending?.fingerprint === fingerprint ? pending.key : makeKey();
    pendingOperationKeys.set(operationScope, { fingerprint, key });

    const result = await jsonMutation<T>(
      path,
      body,
      extraHeaders,
      method,
      key,
      signal,
    );
    if (pendingOperationKeys.get(operationScope)?.key === key) {
      pendingOperationKeys.delete(operationScope);
    }
    return result;
  }

  async function rememberAuthenticatedOwner<T>(body: T): Promise<T> {
    ownerLease = null;
    if (isRecord(body) && typeof body.person_id === "string") {
      try {
        const activation = await offlineReadCache?.activateOwner(
          body.person_id,
        );
        ownerLease = activation?.ok ? activation.lease : null;
      } catch {
        // Authentication success must not be made dependent on browser
        // persistence, but a failed binding must not issue a private lease.
        ownerLease = null;
      }
    }
    return body;
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
    loginPassword: async (email: string, password: string) =>
      rememberAuthenticatedOwner(
        await jsonMutation<PasswordSessionResponse>("/v1/auth/password/login", {
          email,
          password,
        }),
      ),
    requestPasswordRecovery: (email: string) =>
      jsonMutation<PasswordRecoveryResponse>("/v1/auth/password/recovery", {
        email,
      }),
    resendPasswordVerification: (email: string) =>
      jsonMutation<PasswordRecoveryResponse>(
        "/v1/auth/password/resend-verification",
        { email },
      ),
    verifyPasswordEmail: async (token: string) =>
      rememberAuthenticatedOwner(
        await jsonMutation<PasswordSessionResponse>(
          "/v1/auth/password/verify",
          {
            token,
          },
        ),
      ),
    resetPassword: (token: string, newPassword: string) =>
      jsonMutation<PasswordResetResponse>("/v1/auth/password/reset", {
        token,
        new_password: newPassword,
      }),
    onboarding: (options: LearnerReadOptions = {}) =>
      request<OnboardingResponse>("/v1/onboarding", {
        ...options,
        cache: "no-store",
      }),
    saveOnboarding: (input: OnboardingSaveInput, expectedRevision: number) =>
      logicalJsonMutation<OnboardingResponse>(
        "onboarding",
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
    me: (options: LearnerReadOptions = {}) =>
      request<MeResponse>("/v1/me", { ...options, cache: "no-store" }),
    communityProfile: (options: LearnerReadOptions = {}) =>
      request<CommunityProfileResponse>("/v1/community/profile", {
        ...options,
        cache: "no-store",
      }),
    claimUsername: (username: string, signal?: AbortSignal) =>
      logicalJsonMutation<CommunityProfileResponse>(
        `community-username:${username.trim().toLowerCase()}`,
        "/v1/community/username",
        { username },
        {},
        "PUT",
        signal,
      ),
    setLeaderboardOptIn: (
      optedIn: boolean,
      expectedRevision: number,
      signal?: AbortSignal,
    ) =>
      logicalJsonMutation<CommunityProfileResponse>(
        `community-leaderboard-opt-in:${expectedRevision}:${String(optedIn)}`,
        "/v1/community/leaderboard-opt-in",
        { opted_in: optedIn, expected_revision: expectedRevision },
        {},
        "PUT",
        signal,
      ),
    communityLeaderboard: (
      limit = 25,
      cursor?: string,
      options: LearnerReadOptions = {},
    ) => {
      const query = new URLSearchParams({ limit: String(limit) });
      if (cursor) query.set("cursor", cursor);
      return request<CommunityLeaderboardResponse>(
        `/v1/community/leaderboard?${query.toString()}`,
        { ...options, cache: "no-store" },
      );
    },
    profileAvatar: (options: LearnerReadOptions = {}) =>
      request<ProfileAvatarResponse>("/v1/profile/avatar", {
        ...options,
        cache: "no-store",
      }),
    createProfileAvatarUpload: (
      input: ProfileAvatarUploadInput,
      signal?: AbortSignal,
    ) =>
      logicalJsonMutation<AvatarUploadIntentResponse>(
        "profile-avatar-upload",
        "/v1/profile/avatar",
        {
          purpose: "avatar",
          filename: input.filename,
          content_type: input.content_type,
          content_length: input.content_length,
          checksum_sha256: input.checksum_sha256,
          ...(input.asset_id ? { asset_id: input.asset_id } : {}),
          ...(input.supersedes_version_id
            ? { supersedes_version_id: input.supersedes_version_id }
            : {}),
          ...(input.crop ? { crop: input.crop } : {}),
        },
        {},
        "POST",
        signal,
      ),
    completeProfileAvatarUpload: (
      uploadId: string,
      input: {
        actual_bytes?: number;
        checksum_sha256?: string;
        storage_version_id?: string;
        width?: number;
        height?: number;
      } = {},
      signal?: AbortSignal,
    ) =>
      logicalJsonMutation<MediaAssetResponse>(
        `profile-avatar-complete:${uploadId}`,
        `/v1/profile/avatar/${encodeURIComponent(uploadId)}/complete`,
        {
          ...(input.actual_bytes ? { actual_bytes: input.actual_bytes } : {}),
          ...(input.checksum_sha256
            ? { checksum_sha256: input.checksum_sha256 }
            : {}),
          ...(input.storage_version_id
            ? { storage_version_id: input.storage_version_id }
            : {}),
          ...(input.width ? { width: input.width } : {}),
          ...(input.height ? { height: input.height } : {}),
        },
        {},
        "POST",
        signal,
      ),
    context: (options: LearnerReadOptions = {}) =>
      request<ContextResponse>("/v1/context", {
        ...options,
        cache: "no-store",
      }),
    listPrograms: (limit = 50, options: LearnerReadOptions = {}) =>
      request<ProgramCollectionResponse>(`/v1/programs?limit=${limit}`, {
        ...options,
        cache: "no-store",
      }),
    learningCollection: (
      limit = 50,
      options: LearningCollectionReadOptions = {},
    ) => {
      const { cursor, ...requestOptions } = options;
      const query = new URLSearchParams({ limit: String(limit) });
      if (cursor) query.set("cursor", cursor);
      return request<LearningCollectionResponse>(
        `/v1/learning?${query.toString()}`,
        {
          ...requestOptions,
          cache: "no-store",
        },
      );
    },
    program: (slug: string, options: LearnerReadOptions = {}) =>
      request<ProgramDetailResponse>(
        `/v1/programs/${encodeURIComponent(slug)}`,
        {
          ...options,
          cache: "no-store",
        },
      ),
    enrollFree: (programVersionId: string) =>
      // The browser supplies the Origin header for this same-origin POST;
      // Origin is a forbidden header and must not be forged by app code.
      logicalJsonMutation<FreeEnrollmentResponse>(
        `enrollment:${programVersionId}`,
        "/v1/enrollments/free",
        { program_version_id: programVersionId },
      ),
    learning: (
      programId: string,
      scope?: { enrollmentId: string; programVersionId: string },
      options: LearnerReadOptions = {},
    ) => {
      const query = scope
        ? `?${new URLSearchParams({
            enrollment_id: scope.enrollmentId,
            program_version_id: scope.programVersionId,
          }).toString()}`
        : "";
      return request<LearningResponse>(
        `/v1/learning/${encodeURIComponent(programId)}${query}`,
        { ...options, cache: "no-store" },
      );
    },
    calendar: (options: LearnerReadOptions = {}) =>
      request<CalendarResponse>("/v1/learning/calendar", {
        ...options,
        cache: "no-store",
      }),
    insights: (period?: PlanningPeriod, options: LearnerReadOptions = {}) => {
      const query = period ? `?period=${encodeURIComponent(period)}` : "";
      return request<AnalyticsViewResponse>(`/v1/learning/insights${query}`, {
        ...options,
        cache: "no-store",
      });
    },
    activity: (activityId: string, options: LearnerReadOptions = {}) =>
      request<ActivityResponse>(
        `/v1/activities/${encodeURIComponent(activityId)}`,
        {
          ...options,
          cache: "no-store",
        },
      ),
    saveDraft: (activityId: string, payload: JsonRecord, revision: number) =>
      logicalJsonMutation<DraftResponse>(
        `draft:${activityId}`,
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
      playbackSessionId?: string,
      playbackToken?: string,
    ) =>
      logicalJsonMutation<EvidenceResponse>(
        `evidence:${activityId}`,
        `/v1/activities/${encodeURIComponent(activityId)}/evidence`,
        {
          evidence_type: evidenceType,
          payload,
          ...(playbackSessionId
            ? { playback_session_id: playbackSessionId }
            : {}),
          ...(playbackToken ? { playback_token: playbackToken } : {}),
        },
        { "If-Match": `\"activity-revision-${revision}\"` },
      ),
    startPlayback: (activityId: string, revision: number) =>
      logicalJsonMutation<PlaybackStartResponse>(
        `playback-start:${activityId}`,
        `/v1/activities/${encodeURIComponent(activityId)}/playback/start`,
        {},
        { "If-Match": `\"activity-revision-${revision}\"` },
      ),
    heartbeatPlayback: (
      activityId: string,
      input: PlaybackEventInput,
      playbackToken: string,
    ) =>
      logicalJsonMutation<PlaybackEventResponse>(
        `playback-heartbeat:${activityId}:${input.session_id}:${input.event_id}`,
        `/v1/activities/${encodeURIComponent(activityId)}/playback/heartbeat`,
        { ...input },
        { "X-Playback-Token": playbackToken },
      ),
    finishPlayback: (
      activityId: string,
      sessionId: string,
      revision: number,
      playbackToken: string,
    ) =>
      logicalJsonMutation<PlaybackFinishResponse>(
        `playback-finish:${activityId}:${sessionId}`,
        `/v1/activities/${encodeURIComponent(activityId)}/playback/finish`,
        { session_id: sessionId },
        {
          "If-Match": `\"playback-revision-${revision}\"`,
          "X-Playback-Token": playbackToken,
        },
      ),
    certificate: (certificateId: string, options: LearnerReadOptions = {}) =>
      request<CertificateResponse>(
        `/v1/certificates/${encodeURIComponent(certificateId)}`,
        { ...options, cache: "no-store" },
      ),
    logout: async () => {
      try {
        await request<void>("/v1/auth/logout", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
        });
      } catch (error) {
        // The API intentionally reports local-only sign-out when revocation
        // could not be confirmed. The browser is still signed out, so clear
        // bounded local copies just as the UI does after handling this code.
        if (
          !(error instanceof ApiError) ||
          error.code !== "logout_revocation_unavailable"
        ) {
          throw error;
        }
        try {
          await offlineReadCache?.purge();
        } catch {
          // SignOutControl performs the user-visible cleanup check and retry.
        }
        ownerLease = null;
        throw error;
      }
      try {
        await offlineReadCache?.purge();
      } catch {
        // SignOutControl performs the user-visible cleanup check and retry.
      }
      ownerLease = null;
    },
  };
}

export type LearnerApi = ReturnType<typeof createLearnerApi>;
