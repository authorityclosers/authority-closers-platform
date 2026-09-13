import { z } from "zod";

export const REVIEW_ASSIGNMENT_SCHEMA =
  "ac.sales-xray.review-assignment/1" as const;
export const REVIEW_ASSIGNMENT_CREATE_SCHEMA =
  "ac.sales-xray.review-assignment-create/1" as const;

const academyOrigins = new Set([
  "http://localhost:3000",
  "http://learner.localhost:3000",
  "http://learner.localhost:3100",
  "https://staging.authorityclosers.com",
  "https://learner-staging.authorityclosers.com",
  "https://app.authorityclosers.com",
  "https://learner.authorityclosers.com",
]);

export const reviewLenses = ["sales", "technical", "ux"] as const;
export type ReviewMode = (typeof reviewLenses)[number];

export const assignmentStates = [
  "assigned",
  "in_progress",
  "submitted",
  "revoked",
  "expired",
] as const;
export type AssignmentState = (typeof assignmentStates)[number];

const uuidSchema = z
  .uuid()
  .refine(
    (value) => value === value.toLowerCase(),
    "UUID must be canonical lowercase.",
  );
const digestSchema = z.string().regex(/^[0-9a-f]{64}$/);

const sourceSchema = z
  .object({
    tenant_id: uuidSchema,
    recording_id: uuidSchema,
    source_sha256: digestSchema,
    source_revision: z.number().int().positive(),
    permission_id: uuidSchema,
    provenance_ref: z
      .string()
      .regex(/^ref:[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$/),
  })
  .strict();

const checkpointSchema = z
  .object({
    id: uuidSchema,
    tenant_id: uuidSchema,
    recording_id: uuidSchema,
    source_sha256: digestSchema,
    source_revision: z.number().int().positive(),
    stage: z.enum(["C0", "C1", "C2", "C3", "C4", "C5", "C6"]),
    revision: z.string().min(1).max(128),
    cache_key: digestSchema,
    manifest_sha256: digestSchema,
    payload_sha256: digestSchema,
  })
  .strict();

export const reviewAssignmentSchema = z
  .object({
    schema_id: z.literal(REVIEW_ASSIGNMENT_SCHEMA),
    id: uuidSchema,
    tenant_id: uuidSchema,
    run_id: uuidSchema,
    run_generation: z.number().int().positive(),
    recipe_revision: z.string().min(1).max(128),
    source: sourceSchema,
    checkpoint: checkpointSchema,
    reviewer_person_id: uuidSchema,
    allowed_lenses: z.array(z.enum(reviewLenses)).min(1).max(3),
    state: z.enum(assignmentStates),
    created_at_epoch: z.number().int().positive(),
    expires_at_epoch: z.number().int().positive(),
    created_by_person_id: uuidSchema,
  })
  .strict()
  .superRefine((value, context) => {
    if (value.expires_at_epoch <= value.created_at_epoch) {
      context.addIssue({
        code: "custom",
        path: ["expires_at_epoch"],
        message: "assignment expiry must follow creation",
      });
    }
    if (new Set(value.allowed_lenses).size !== value.allowed_lenses.length) {
      context.addIssue({
        code: "custom",
        path: ["allowed_lenses"],
        message: "assignment lenses must be unique",
      });
    }
    if (value.source.tenant_id !== value.tenant_id) {
      context.addIssue({
        code: "custom",
        path: ["source", "tenant_id"],
        message: "source tenant differs from assignment tenant",
      });
    }
    if (
      value.checkpoint.tenant_id !== value.tenant_id ||
      value.checkpoint.recording_id !== value.source.recording_id ||
      value.checkpoint.source_sha256 !== value.source.source_sha256 ||
      value.checkpoint.source_revision !== value.source.source_revision
    ) {
      context.addIssue({
        code: "custom",
        path: ["checkpoint"],
        message: "checkpoint is not bound to the assignment source",
      });
    }
  });

/** FastAPI uses the field alias (`schema`) on the HTTP wire. Keep one normalized
 * internal shape so the workspace can render either contract revision safely. */
const reviewAssignmentResponseSchema = z.preprocess((value) => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return value;
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.schema !== REVIEW_ASSIGNMENT_SCHEMA) return value;
  const { schema, ...rest } = candidate;
  return { ...rest, schema_id: schema };
}, reviewAssignmentSchema);

const reviewAssignmentsSchema = z
  .object({ items: z.array(reviewAssignmentResponseSchema) })
  .strict();

export type ReviewAssignment = z.infer<typeof reviewAssignmentSchema>;
export type ReviewAssignmentsPayload = z.infer<typeof reviewAssignmentsSchema>;

export type ReviewQueueState =
  | { status: "loading"; items: readonly ReviewAssignment[] }
  | { status: "ready"; items: readonly ReviewAssignment[] }
  | {
      status: "error";
      items: readonly ReviewAssignment[];
      message: string;
      retryable: boolean;
    };

export class ReviewApiProblem extends Error {
  readonly status: number;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor({
    status,
    requestId,
    detail,
  }: {
    status: number;
    requestId: string | null;
    detail: string;
  }) {
    super(detail);
    this.name = "ReviewApiProblem";
    this.status = status;
    this.requestId = requestId;
    this.retryable = status >= 500 || status === 408 || status === 429;
  }
}

type Fetcher = typeof fetch;

function currentOrigin(): string | undefined {
  return typeof window === "undefined" ? undefined : window.location.origin;
}

function assertUuid(value: string, label: string): string {
  const parsed = uuidSchema.safeParse(value);
  if (!parsed.success) throw new TypeError(`${label} must be a UUID.`);
  return parsed.data;
}

function assertIdempotencyKey(value: string): string {
  if (
    !value ||
    value.length > 128 ||
    value.trim() !== value ||
    !/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$/.test(value)
  ) {
    throw new TypeError("idempotencyKey must be a bounded request key.");
  }
  return value;
}

export function newReviewIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  throw new Error("Secure idempotency key generation is unavailable.");
}

async function parseProblem(response: Response): Promise<ReviewApiProblem> {
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
      : "The review assignment request was rejected.";
  return new ReviewApiProblem({
    status: response.status,
    requestId:
      typeof candidate.request_id === "string" ? candidate.request_id : null,
    detail,
  });
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>,
  fetcher: Fetcher,
): Promise<T> {
  const response = await fetcher(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
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

export function loadReviewAssignments(
  fetcher: Fetcher = fetch,
  signal?: AbortSignal,
): Promise<ReviewAssignmentsPayload> {
  return requestJson(
    "/v1/admin/conversation/review-assignments?limit=50",
    {
      method: "GET",
      headers: { accept: "application/json" },
      signal,
    },
    reviewAssignmentsSchema,
    fetcher,
  );
}

export type CreateReviewAssignmentInput = Readonly<{
  runId: string;
  reviewerPersonId: string;
  allowedLenses: readonly ReviewMode[];
  expiresAtEpoch: number;
  idempotencyKey: string;
  origin?: string;
  fetcher?: Fetcher;
  signal?: AbortSignal;
}>;

function receiptMismatch(message: string): Error & { retryable: false } {
  const error = new Error(message) as Error & { retryable: false };
  error.retryable = false;
  return error;
}

function assertCreateReceipt(
  assignment: ReviewAssignment,
  expected: Readonly<{
    runId: string;
    reviewerPersonId: string;
    allowedLenses: readonly ReviewMode[];
    expiresAtEpoch: number;
  }>,
): ReviewAssignment {
  if (
    assignment.run_id !== expected.runId ||
    assignment.reviewer_person_id !== expected.reviewerPersonId ||
    assignment.expires_at_epoch !== expected.expiresAtEpoch ||
    assignment.allowed_lenses.length !== expected.allowedLenses.length ||
    assignment.allowed_lenses.some(
      (lens, index) => lens !== expected.allowedLenses[index],
    )
  ) {
    throw receiptMismatch(
      "The server returned an assignment that does not match the requested reviewer handoff.",
    );
  }
  return assignment;
}

function assertRevokeReceipt(
  assignment: ReviewAssignment,
  assignmentId: string,
): ReviewAssignment {
  if (assignment.id !== assignmentId || assignment.state !== "revoked") {
    throw receiptMismatch(
      "The server did not confirm revocation of the requested assignment.",
    );
  }
  return assignment;
}

export function createReviewAssignment({
  runId,
  reviewerPersonId,
  allowedLenses,
  expiresAtEpoch,
  idempotencyKey,
  origin = currentOrigin(),
  fetcher = fetch,
  signal,
}: CreateReviewAssignmentInput): Promise<ReviewAssignment> {
  const checkedRunId = assertUuid(runId, "runId");
  const checkedReviewerPersonId = assertUuid(
    reviewerPersonId,
    "reviewerPersonId",
  );
  const lenses = z
    .array(z.enum(reviewLenses))
    .min(1)
    .max(3)
    .parse([...allowedLenses]);
  if (new Set(lenses).size !== lenses.length) {
    throw new TypeError("allowedLenses must not contain duplicates.");
  }
  const expires = z.number().int().positive().parse(expiresAtEpoch);
  const key = assertIdempotencyKey(idempotencyKey);
  const headers = new Headers({
    accept: "application/json",
    "content-type": "application/json",
    "Idempotency-Key": key,
  });
  if (origin) headers.set("origin", origin);
  return requestJson(
    "/v1/admin/conversation/review-assignments",
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        schema: REVIEW_ASSIGNMENT_CREATE_SCHEMA,
        run_id: checkedRunId,
        reviewer_person_id: checkedReviewerPersonId,
        allowed_lenses: lenses,
        expires_at_epoch: expires,
      }),
      signal,
    },
    reviewAssignmentResponseSchema,
    fetcher,
  ).then((assignment) =>
    assertCreateReceipt(assignment, {
      runId: checkedRunId,
      reviewerPersonId: checkedReviewerPersonId,
      allowedLenses: lenses,
      expiresAtEpoch: expires,
    }),
  );
}

export type RevokeReviewAssignmentInput = Readonly<{
  assignmentId: string;
  idempotencyKey: string;
  origin?: string;
  fetcher?: Fetcher;
  signal?: AbortSignal;
}>;

export function revokeReviewAssignment({
  assignmentId,
  idempotencyKey,
  origin = currentOrigin(),
  fetcher = fetch,
  signal,
}: RevokeReviewAssignmentInput): Promise<ReviewAssignment> {
  const checkedId = assertUuid(assignmentId, "assignmentId");
  const key = assertIdempotencyKey(idempotencyKey);
  const headers = new Headers({
    accept: "application/json",
    "Idempotency-Key": key,
  });
  if (origin) headers.set("origin", origin);
  return requestJson(
    `/v1/admin/conversation/review-assignments/${encodeURIComponent(checkedId)}/revoke`,
    { method: "POST", headers, signal },
    reviewAssignmentResponseSchema,
    fetcher,
  ).then((assignment) => assertRevokeReceipt(assignment, checkedId));
}

export function reviewError(error: unknown): {
  message: string;
  retryable: boolean;
} {
  if (error instanceof ReviewApiProblem) {
    return { message: error.message, retryable: error.retryable };
  }
  if (error instanceof Error) {
    return {
      message: error.message || "The review queue could not be loaded.",
      retryable: (error as Error & { retryable?: boolean }).retryable ?? true,
    };
  }
  return {
    message:
      "The review queue could not be loaded. Retry when the service is available.",
    retryable: true,
  };
}

/** Build a reviewer handoff only from the deployment-owned Academy origin. */
export function buildAcademyReviewLink(
  academyOrigin: string | null | undefined,
  assignmentId: string,
): string | null {
  const trustedOrigin = academyAppOrigin(academyOrigin ?? undefined);
  if (!trustedOrigin || !assignmentId) return null;
  try {
    const url = new URL(
      `/sales-xray/review/${encodeURIComponent(assignmentId)}`,
      trustedOrigin,
    );
    if (url.origin !== trustedOrigin) return null;
    return url.toString();
  } catch {
    return null;
  }
}

/** Validate the deployment-owned learner/Academy origin before creating a link. */
export function academyAppOrigin(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value.trim());
    if (
      !["http:", "https:"].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash ||
      (parsed.pathname !== "" && parsed.pathname !== "/") ||
      !academyOrigins.has(parsed.origin)
    ) {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}
