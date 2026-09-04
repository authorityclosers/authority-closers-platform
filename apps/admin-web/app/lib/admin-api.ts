import { z } from "zod";

const adminRoleSchema = z.enum(["owner", "admin", "support", "learner"]);

const meSchema = z
  .object({
    person_id: z.uuid(),
    email: z.string().email(),
    display_name: z.string().nullable(),
    email_verified_at: z.string().min(1),
    selected_tenant_id: z.uuid().nullable(),
    membership_role: adminRoleSchema.nullable(),
    permissions: z.array(z.string().min(1).max(64)).max(64),
  })
  .strict();

const contextSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    tenant_id: z.uuid().nullable(),
    membership_role: adminRoleSchema.nullable(),
    permissions: z.array(z.string().min(1).max(64)).max(64),
  })
  .strict();

export type AdminPermission =
  | "admin_surface"
  | "catalog_read"
  | "catalog_publish"
  | "learner_diagnose"
  | "learning_correct"
  | "enrollment_grant"
  | "job_retry"
  | "recovery_reconcile";

export type AdminMe = z.infer<typeof meSchema>;
export type AdminContext = z.infer<typeof contextSchema>;

export type AdminSession = Readonly<{
  personId: string;
  email: string;
  displayName: string | null;
  emailVerifiedAt: string;
  sessionId: string;
  tenantId: string;
  membershipRole: "owner" | "admin" | "support";
  permissions: readonly string[];
}>;

export class AdminApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly title: string;

  constructor({
    status,
    code,
    requestId,
    title,
    detail,
  }: {
    status: number;
    code: string;
    requestId: string | null;
    title: string;
    detail: string;
  }) {
    super(detail);
    this.name = "AdminApiProblem";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.title = title;
  }
}

export class AdminSessionDenied extends Error {
  readonly code = "admin_session_denied";

  constructor(
    detail = "The product session is not authorized for this admin surface.",
  ) {
    super(detail);
    this.name = "AdminSessionDenied";
  }
}

type Fetcher = typeof fetch;

function assertSameOriginPath(path: string): string {
  if (!path.startsWith("/v1/") || path.startsWith("//")) {
    throw new TypeError("Admin API requests must use a same-origin /v1 path.");
  }
  return path;
}

function currentOrigin(): string | undefined {
  return typeof window === "undefined" ? undefined : window.location.origin;
}

function mutationHeaders({
  origin,
  idempotencyKey,
  ifMatch,
  hasBody,
}: {
  origin?: string;
  idempotencyKey?: string;
  ifMatch?: string;
  hasBody: boolean;
}): Headers {
  const headers = new Headers({ accept: "application/json" });
  if (hasBody) headers.set("content-type", "application/json");
  if (origin) headers.set("origin", origin);
  if (idempotencyKey) headers.set("idempotency-key", idempotencyKey);
  if (ifMatch) headers.set("if-match", ifMatch);
  return headers;
}

async function parseProblem(response: Response): Promise<AdminApiProblem> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const candidate =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const detail =
    typeof candidate.detail === "string" && candidate.detail.trim()
      ? candidate.detail
      : "The admin request was rejected.";
  const title =
    typeof candidate.title === "string" && candidate.title.trim()
      ? candidate.title
      : "Admin request rejected";
  const code =
    typeof candidate.code === "string" && candidate.code.trim()
      ? candidate.code
      : `http_${response.status}`;
  const requestId =
    typeof candidate.request_id === "string" ? candidate.request_id : null;
  return new AdminApiProblem({
    status: response.status,
    code,
    requestId,
    title,
    detail,
  });
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>,
  fetcher: Fetcher = fetch,
): Promise<T> {
  const response = await fetcher(assertSameOriginPath(path), {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) throw await parseProblem(response);
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }
  return schema.parse(payload);
}

async function requestSessionJson<T>(
  path: "/v1/me" | "/v1/context",
  fetcher: Fetcher,
) {
  const response = await fetcher(path, {
    method: "GET",
    cache: "no-store",
    credentials: "same-origin",
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw await parseProblem(response);
  return response.json() as Promise<T>;
}

export async function loadAdminSession(
  fetcher: Fetcher = fetch,
): Promise<AdminSession> {
  let me: AdminMe;
  let context: AdminContext;
  try {
    me = meSchema.parse(await requestSessionJson<unknown>("/v1/me", fetcher));
    context = contextSchema.parse(
      await requestSessionJson<unknown>("/v1/context", fetcher),
    );
  } catch (error) {
    if (error instanceof AdminApiProblem) {
      throw new AdminSessionDenied(
        "The product session could not be verified.",
      );
    }
    throw new AdminSessionDenied();
  }

  const role = context.membership_role;
  const permissions = [...new Set(context.permissions)].sort();
  const mePermissions = new Set(me.permissions);
  const isAdminRole =
    role === "owner" || role === "admin" || role === "support";
  const consistent =
    me.person_id === context.person_id &&
    me.selected_tenant_id === context.tenant_id &&
    Boolean(context.tenant_id) &&
    me.membership_role === context.membership_role;
  if (
    !isAdminRole ||
    !permissions.includes("admin_surface") ||
    !mePermissions.has("admin_surface") ||
    !consistent
  ) {
    throw new AdminSessionDenied();
  }

  return {
    personId: me.person_id,
    email: me.email,
    displayName: me.display_name,
    emailVerifiedAt: me.email_verified_at,
    sessionId: context.session_id,
    tenantId: context.tenant_id as string,
    membershipRole: role,
    permissions,
  };
}

function body(value: unknown): string {
  return JSON.stringify(value);
}

function uuidPath(value: string, label: string): string {
  const parsed = z.uuid().safeParse(value);
  if (!parsed.success)
    throw new TypeError(`${label} must be a UUID resolved by the server.`);
  return encodeURIComponent(parsed.data);
}

export type PublishProgramVersionInput = Readonly<{
  programVersionId: string;
  reason: string;
  ifMatch: string;
  idempotencyKey: string;
  origin?: string;
  fetcher?: Fetcher;
}>;

export type CorrectionInput = Readonly<{
  submissionId: string;
  decision: "approved" | "rejected" | "needs_revision";
  reason: string;
  ifMatch: string;
  idempotencyKey: string;
  origin?: string;
  fetcher?: Fetcher;
}>;

export type EnrollmentGrantInput = Readonly<{
  personId: string;
  programVersionId: string;
  reason: string;
  idempotencyKey: string;
  origin?: string;
  fetcher?: Fetcher;
}>;

export type RetryJobInput = Readonly<{
  jobId: string;
  reason: string;
  idempotencyKey: string;
  origin?: string;
  fetcher?: Fetcher;
}>;

export type ReconcileRecoveryInput = Readonly<{
  jobIds: readonly string[];
  outboxEventIds: readonly string[];
  reason: string;
  idempotencyKey: string;
  origin?: string;
  fetcher?: Fetcher;
}>;

const publishProgramVersionResponseSchema = z
  .object({
    id: z.uuid(),
    program_id: z.uuid(),
    version_number: z.number().int(),
    status: z.literal("published"),
    supersedes_version_id: z.uuid().nullable(),
    published_at: z.string().min(1),
    replayed: z.boolean(),
  })
  .strict();

const unavailableMetricSchema = z
  .object({
    status: z.literal("unavailable"),
    value: z.null(),
    reason: z.string().min(1),
  })
  .strict();

const draftReadinessSchema = z
  .object({
    program_id: z.uuid(),
    program_title: z.string().min(1),
    program_version_id: z.uuid(),
    version_number: z.number().int().positive(),
    created_at: z.string().min(1),
    age_seconds: z.number().int().nonnegative(),
    etag: z.string().regex(/^"program-version-[0-9a-f]{64}"$/),
    ready: z.boolean(),
    blockers: z.array(z.string().min(1)),
  })
  .strict();

const studioReadinessSchema = z
  .object({
    tenant_id: z.uuid(),
    draft_backlog_count: z.number().int().nonnegative(),
    as_of: z.string().min(1),
    oldest_draft_created_at: z.string().min(1).nullable(),
    oldest_draft_age_seconds: z.number().int().nonnegative().nullable(),
    drafts: z.array(draftReadinessSchema),
    truncated: z.boolean(),
    arrival_rate: unavailableMetricSchema,
    service_rate: unavailableMetricSchema,
    planned_capacity: unavailableMetricSchema,
  })
  .strict();

const programVersionSummarySchema = z
  .object({
    id: z.uuid(),
    version_number: z.number().int().positive(),
    status: z.enum(["draft", "published", "superseded"]),
    created_at: z.string().min(1),
    published_at: z.string().min(1).nullable(),
  })
  .strict();

const programSummarySchema = z
  .object({
    id: z.uuid(),
    slug: z.string().min(1),
    title: z.string().min(1),
    scope: z.enum(["tenant", "global"]),
    access: z.enum(["selected_tenant", "global_read_only"]),
    version_count: z.number().int().nonnegative(),
    draft_count: z.number().int().nonnegative(),
    current_published_version_id: z.uuid().nullable(),
    latest_version: programVersionSummarySchema.nullable(),
  })
  .strict();

const studioProgramsSchema = z
  .object({
    tenant_id: z.uuid(),
    programs: z.array(programSummarySchema),
    truncated: z.boolean(),
  })
  .strict();

const activitySchema = z
  .object({
    id: z.uuid(),
    position: z.number().int().nonnegative(),
    kind: z.string().min(1),
    title: z.string().min(1),
    prompt: z.string().nullable(),
    is_required: z.boolean(),
  })
  .strict();

const moduleSchema = z
  .object({
    id: z.uuid(),
    position: z.number().int().nonnegative(),
    title: z.string().min(1),
    prerequisite_module_ids: z.array(z.uuid()),
    activities: z.array(activitySchema),
  })
  .strict();

const programVersionSchema = programVersionSummarySchema.extend({
  supersedes_version_id: z.uuid().nullable(),
  content_source_ref: z.string().nullable(),
  content_reviewed_by: z.string().nullable(),
  content_reviewed_at: z.string().min(1).nullable(),
  release_id: z.string().nullable(),
  content_seed_kind: z.string().nullable(),
  content_digest: z
    .string()
    .regex(/^[0-9a-f]{64}$/)
    .nullable(),
  etag: z
    .string()
    .regex(/^"program-version-[0-9a-f]{64}"$/)
    .nullable(),
  readiness: z.enum(["ready", "blocked", "immutable", "global_read_only"]),
  blockers: z.array(z.string().min(1)),
  modules: z.array(moduleSchema),
});

const studioProgramDetailSchema = z
  .object({
    tenant_id: z.uuid(),
    id: z.uuid(),
    slug: z.string().min(1),
    title: z.string().min(1),
    scope: z.enum(["tenant", "global"]),
    access: z.enum(["selected_tenant", "global_read_only"]),
    versions: z.array(programVersionSchema),
    versions_truncated: z.boolean(),
  })
  .strict();

const correctionResponseSchema = z
  .object({
    correction_id: z.uuid(),
    submission_id: z.uuid(),
    decision: z.enum(["approved", "rejected", "needs_revision"]),
    correction_sequence: z.number().int(),
    supersedes_correction_id: z.uuid().nullable(),
  })
  .strict();

const enrollmentGrantResponseSchema = z
  .object({
    enrollment_id: z.uuid(),
    entitlement_id: z.uuid(),
    provenance_id: z.uuid(),
    command_idempotency_id: z.uuid(),
    created: z.boolean(),
    replayed: z.boolean(),
  })
  .strict();

const jobRetryResponseSchema = z
  .object({
    job_id: z.uuid(),
    status: z.string().min(1),
    attempt_count: z.number().int(),
    recovery_generation: z.number().int(),
    held: z.boolean(),
    replayed: z.boolean(),
  })
  .strict();

const recoveryReconcileResponseSchema = z
  .object({
    job_ids: z.array(z.uuid()),
    outbox_event_ids: z.array(z.uuid()),
    recovery_generation: z.number().int(),
    recovery_status: z.string().min(1),
    replayed: z.boolean(),
  })
  .strict();

export type ProgramVersionPublishResponse = z.infer<
  typeof publishProgramVersionResponseSchema
>;
export type StudioReadiness = z.infer<typeof studioReadinessSchema>;
export type StudioPrograms = z.infer<typeof studioProgramsSchema>;
export type StudioProgramDetail = z.infer<typeof studioProgramDetailSchema>;
export type CorrectionResponse = z.infer<typeof correctionResponseSchema>;
export type EnrollmentGrantResponse = z.infer<
  typeof enrollmentGrantResponseSchema
>;
export type JobRetryResponse = z.infer<typeof jobRetryResponseSchema>;
export type RecoveryReconcileResponse = z.infer<
  typeof recoveryReconcileResponseSchema
>;

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  throw new Error("Secure idempotency key generation is unavailable.");
}

export function publishProgramVersion({
  programVersionId,
  reason,
  ifMatch,
  idempotencyKey,
  origin = currentOrigin(),
  fetcher = fetch,
}: PublishProgramVersionInput) {
  return requestJson<ProgramVersionPublishResponse>(
    "/v1/admin/program-versions/" +
      uuidPath(programVersionId, "programVersionId") +
      "/publish",
    {
      method: "POST",
      headers: mutationHeaders({
        origin,
        ifMatch,
        idempotencyKey,
        hasBody: true,
      }),
      body: body({ reason }),
    },
    publishProgramVersionResponseSchema,
    fetcher,
  );
}

export function loadStudioReadiness(fetcher: Fetcher = fetch) {
  return requestJson(
    "/v1/admin/studio/readiness",
    { method: "GET", headers: { accept: "application/json" } },
    studioReadinessSchema,
    fetcher,
  );
}

export function loadStudioPrograms(fetcher: Fetcher = fetch) {
  return requestJson(
    "/v1/admin/studio/programs",
    { method: "GET", headers: { accept: "application/json" } },
    studioProgramsSchema,
    fetcher,
  );
}

export function loadStudioProgram(programId: string, fetcher: Fetcher = fetch) {
  return requestJson(
    "/v1/admin/studio/programs/" + uuidPath(programId, "programId"),
    { method: "GET", headers: { accept: "application/json" } },
    studioProgramDetailSchema,
    fetcher,
  );
}

export function appendCorrection({
  submissionId,
  decision,
  reason,
  ifMatch,
  idempotencyKey,
  origin = currentOrigin(),
  fetcher = fetch,
}: CorrectionInput) {
  return requestJson<CorrectionResponse>(
    "/v1/admin/corrections",
    {
      method: "POST",
      headers: mutationHeaders({
        origin,
        idempotencyKey,
        ifMatch,
        hasBody: true,
      }),
      body: body({
        submission_id: uuidPath(submissionId, "submissionId"),
        decision,
        reason,
      }),
    },
    correctionResponseSchema,
    fetcher,
  );
}

export function grantEnrollment({
  personId,
  programVersionId,
  reason,
  idempotencyKey,
  origin = currentOrigin(),
  fetcher = fetch,
}: EnrollmentGrantInput) {
  return requestJson<EnrollmentGrantResponse>(
    "/v1/admin/enrollment-grants",
    {
      method: "POST",
      headers: mutationHeaders({ origin, idempotencyKey, hasBody: true }),
      body: body({
        person_id: uuidPath(personId, "personId"),
        program_version_id: uuidPath(programVersionId, "programVersionId"),
        reason,
      }),
    },
    enrollmentGrantResponseSchema,
    fetcher,
  );
}

export function retryJob({
  jobId,
  reason,
  idempotencyKey,
  origin = currentOrigin(),
  fetcher = fetch,
}: RetryJobInput) {
  return requestJson<JobRetryResponse>(
    "/v1/admin/jobs/" + uuidPath(jobId, "jobId") + "/retry",
    {
      method: "POST",
      headers: mutationHeaders({ origin, idempotencyKey, hasBody: true }),
      body: body({ reason }),
    },
    jobRetryResponseSchema,
    fetcher,
  );
}

export function reconcileRecovery({
  jobIds,
  outboxEventIds,
  reason,
  idempotencyKey,
  origin = currentOrigin(),
  fetcher = fetch,
}: ReconcileRecoveryInput) {
  return requestJson<RecoveryReconcileResponse>(
    "/v1/admin/recovery/reconcile",
    {
      method: "POST",
      headers: mutationHeaders({ origin, idempotencyKey, hasBody: true }),
      body: body({
        job_ids: jobIds.map((value) => uuidPath(value, "jobId")),
        outbox_event_ids: outboxEventIds.map((value) =>
          uuidPath(value, "outboxEventId"),
        ),
        reason,
      }),
    },
    recoveryReconcileResponseSchema,
    fetcher,
  );
}
