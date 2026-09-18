import { z } from "zod";

import {
  ReviewApiProblem,
  reviewAssignmentSchema,
  reviewLenses,
  type ReviewAssignment,
} from "./review-api";

const uuidSchema = z
  .uuid()
  .refine(
    (value) => value === value.toLowerCase(),
    "UUID must be canonical lowercase.",
  );
const digestSchema = z.string().regex(/^[0-9a-f]{64}$/);
const assignmentWireSchema = z.preprocess((value) => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return value;
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.schema !== "ac.sales-xray.review-assignment/1") return value;
  const { schema, ...rest } = candidate;
  return { ...rest, schema_id: schema };
}, reviewAssignmentSchema);

const feedbackSubmissionBodySchema = z
  .object({
    schema_id: z.literal("ac.sales-xray.review-feedback/1"),
    id: uuidSchema,
    assignment_id: uuidSchema,
    tenant_id: uuidSchema,
    run_id: uuidSchema,
    reviewer_person_id: uuidSchema,
    author_person_id: uuidSchema,
    lens: z.enum(reviewLenses),
    lane: z.enum(["sales", "signal"]),
    idempotency_key: z.string().min(1).max(128),
    request_sha256: digestSchema,
    evidence_refs: z
      .array(
        z
          .object({
            checkpoint_id: uuidSchema,
            span_id: z.string().min(1).max(128),
          })
          .strict(),
      )
      .min(1)
      .max(64),
    confidence: z.enum(["low", "medium", "high"]),
    feedback: z.string().min(1).max(4000),
    proposed_correction: z
      .object({
        target_layer: z.enum([
          "context",
          "profile",
          "judge",
          "transcript",
          "measurement",
          "attribution",
          "alignment",
          "ux_metadata",
        ]),
        actual: z.string().min(1).max(512),
        expected: z.string().min(1).max(512),
        rationale: z.string().min(1).max(512),
      })
      .strict()
      .nullable(),
    created_at_epoch: z.number().int().positive(),
  })
  .strict();

const feedbackSubmissionSchema = z.preprocess((value) => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return value;
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.schema !== "ac.sales-xray.review-feedback/1") return value;
  const { schema, ...rest } = candidate;
  return { ...rest, schema_id: schema };
}, feedbackSubmissionBodySchema);

const feedbackItemSchema = z
  .object({
    id: uuidSchema,
    assignment_id: uuidSchema,
    tenant_id: uuidSchema,
    request_sha256: digestSchema,
    payload_sha256: digestSchema,
    created_at_epoch: z.number().int().positive(),
    erased_at_epoch: z.number().int().positive().nullable(),
    state: z.enum(["available", "erased", "unavailable"]),
    payload: feedbackSubmissionSchema.nullable(),
    unavailable_reason: z.string().min(1).max(64).optional(),
  })
  .strict()
  .superRefine((item, context) => {
    if (item.state === "available" && item.payload === null) {
      context.addIssue({
        code: "custom",
        path: ["payload"],
        message: "available feedback needs payload",
      });
    }
    if (item.state === "erased" && item.payload !== null) {
      context.addIssue({
        code: "custom",
        path: ["payload"],
        message: "erased feedback payload must be redacted",
      });
    }
    if (item.state === "unavailable" && item.payload !== null) {
      context.addIssue({
        code: "custom",
        path: ["payload"],
        message: "unavailable feedback payload must be redacted",
      });
    }
  });

const detailsSchema = z
  .object({
    assignment: assignmentWireSchema,
    lifecycle: z
      .object({
        state: z.enum([
          "assigned",
          "in_progress",
          "submitted",
          "revoked",
          "expired",
        ]),
        created_at_epoch: z.number().int().positive(),
        expires_at_epoch: z.number().int().positive(),
        revocation: z
          .object({
            person_id: uuidSchema,
            created_at_epoch: z.number().int().positive(),
          })
          .strict()
          .nullable(),
      })
      .strict(),
    source: z
      .object({
        tenant_id: uuidSchema,
        recording_id: uuidSchema,
        source_sha256: digestSchema,
        source_revision: z.number().int().positive(),
        state: z.enum(["awaiting_upload", "ready", "deleting", "deleted"]),
        content_state: z.enum(["retained", "erased", "unavailable"]),
        permission_expires_at_epoch: z.number().int().positive(),
        retention_until_epoch: z.number().int().positive(),
        permission_revoked_at_epoch: z.number().int().positive().nullable(),
      })
      .strict(),
    review: z
      .object({
        run_id: uuidSchema,
        run_generation: z.number().int().positive(),
        recipe_revision: z.string().min(1).max(128),
        run_state: z.enum([
          "queued",
          "running",
          "completed",
          "cancelled",
          "failed",
        ]),
        report_id: uuidSchema,
        report_state: z.enum(["retained", "erased", "unavailable"]),
        checkpoint_id: uuidSchema,
        checkpoint_state: z.enum(["retained", "erased"]),
      })
      .strict(),
    feedback: z.array(feedbackItemSchema).max(100),
    feedback_count: z.number().int().nonnegative(),
    available_feedback_count: z.number().int().nonnegative(),
    feedback_truncated: z.boolean(),
  })
  .strict();

export type AdminReviewDetails = z.infer<typeof detailsSchema>;
export type AdminReviewFeedbackItem = z.infer<typeof feedbackItemSchema>;

type Fetcher = typeof fetch;

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
  return new ReviewApiProblem({
    status: response.status,
    requestId:
      typeof candidate.request_id === "string" ? candidate.request_id : null,
    detail:
      typeof candidate.detail === "string" && candidate.detail.trim()
        ? candidate.detail
        : "The saved review details could not be loaded.",
  });
}

function assertUuid(value: string): string {
  const parsed = uuidSchema.safeParse(value);
  if (!parsed.success) throw new TypeError("assignmentId must be a UUID.");
  return parsed.data;
}

export async function loadAdminReviewDetails(
  assignmentId: string,
  fetcher: Fetcher = fetch,
  signal?: AbortSignal,
): Promise<AdminReviewDetails> {
  const checkedId = assertUuid(assignmentId);
  const response = await fetcher(
    `/v1/admin/conversation/review-assignments/${encodeURIComponent(checkedId)}`,
    {
      method: "GET",
      headers: { accept: "application/json" },
      cache: "no-store",
      credentials: "same-origin",
      mode: "same-origin",
      redirect: "error",
      signal,
    },
  );
  if (!response.ok) throw await parseProblem(response);
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }
  const details = detailsSchema.parse(payload);
  const bound = details.assignment;
  if (
    bound.id !== checkedId ||
    details.source.tenant_id !== bound.tenant_id ||
    details.source.recording_id !== bound.source.recording_id ||
    details.source.source_sha256 !== bound.source.source_sha256 ||
    details.source.source_revision !== bound.source.source_revision ||
    details.review.run_id !== bound.run_id ||
    details.review.run_generation !== bound.run_generation ||
    details.review.recipe_revision !== bound.recipe_revision ||
    details.review.checkpoint_id !== bound.checkpoint.id ||
    details.lifecycle.state !== bound.state ||
    details.lifecycle.created_at_epoch !== bound.created_at_epoch ||
    details.lifecycle.expires_at_epoch !== bound.expires_at_epoch ||
    details.feedback_count < details.feedback.length ||
    details.feedback_truncated !==
      details.feedback_count > details.feedback.length ||
    details.available_feedback_count !==
      details.feedback.filter((item) => item.state === "available").length ||
    new Set(details.feedback.map((item) => item.id)).size !==
      details.feedback.length ||
    details.feedback.some((item) => {
      const value = item.payload;
      return (
        item.assignment_id !== bound.id ||
        item.tenant_id !== bound.tenant_id ||
        (value !== null &&
          (value.id !== item.id ||
            value.assignment_id !== bound.id ||
            value.tenant_id !== bound.tenant_id ||
            value.run_id !== bound.run_id ||
            value.reviewer_person_id !== bound.reviewer_person_id ||
            value.author_person_id !== bound.reviewer_person_id ||
            value.request_sha256 !== item.request_sha256 ||
            !bound.allowed_lenses.includes(value.lens) ||
            value.evidence_refs.some(
              (ref) => ref.checkpoint_id !== bound.checkpoint.id,
            )))
      );
    })
  )
    throw new Error(
      "The saved feedback does not match this review assignment.",
    );
  return details;
}

export function adminReviewDetailsError(error: unknown): {
  message: string;
  retryable: boolean;
} {
  if (error instanceof ReviewApiProblem) {
    return { message: error.message, retryable: error.retryable };
  }
  if (error instanceof z.ZodError) {
    return {
      message: "The saved review details could not be verified.",
      retryable: false,
    };
  }
  if (error instanceof Error) {
    return {
      message: error.message || "The saved review details could not be loaded.",
      retryable: (error as Error & { retryable?: boolean }).retryable ?? true,
    };
  }
  return {
    message: "The saved review details could not be loaded.",
    retryable: true,
  };
}

export type AdminReviewAssignment = ReviewAssignment;
