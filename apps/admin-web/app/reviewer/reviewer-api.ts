import { z } from "zod";

import {
  CORRECTION_TARGETS,
  type ReviewAssignment as FormAssignment,
  type ReviewProposalDraft,
} from "@ac/sales-xray-review-ui";

const uuid = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
const boundedId = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/);
const digest = z.string().regex(/^[0-9a-f]{64}$/);
const lens = z.enum(["sales", "technical", "ux"]);
const confidence = z.enum(["low", "medium", "high"]);
const evidenceRef = z.object({ checkpoint_id: uuid, span_id: boundedId });
const correction = z.object({
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
});

const source = z.object({
  tenant_id: uuid,
  recording_id: uuid,
  source_sha256: digest,
  source_revision: z.number().int().positive(),
  permission_id: uuid,
  provenance_ref: z.string().min(6).max(256),
});
const checkpoint = z.object({
  id: uuid,
  tenant_id: uuid,
  recording_id: uuid,
  source_sha256: digest,
  source_revision: z.number().int().positive(),
  stage: z.enum(["C0", "C1", "C2", "C3", "C4", "C5", "C6"]),
  revision: z.string().min(1).max(128),
  cache_key: digest,
  manifest_sha256: digest,
  payload_sha256: digest,
});

const assignment = z
  .object({
    schema: z.literal("ac.sales-xray.review-assignment/1"),
    id: uuid,
    tenant_id: uuid,
    run_id: uuid,
    run_generation: z.number().int().positive(),
    recipe_revision: z.string().min(1).max(128),
    source,
    checkpoint,
    reviewer_person_id: uuid,
    allowed_lenses: z.array(lens).min(1).max(3),
    state: z.enum([
      "assigned",
      "in_progress",
      "submitted",
      "revoked",
      "expired",
    ]),
    created_at_epoch: z.number().int().positive(),
    expires_at_epoch: z.number().int().positive(),
    created_by_person_id: uuid,
  })
  .superRefine((value, context) => {
    if (new Set(value.allowed_lenses).size !== value.allowed_lenses.length)
      context.addIssue({
        code: "custom",
        path: ["allowed_lenses"],
        message: "Assignment lenses must be unique.",
      });
    if (value.expires_at_epoch <= value.created_at_epoch)
      context.addIssue({
        code: "custom",
        path: ["expires_at_epoch"],
        message: "Assignment expiry is invalid.",
      });
    if (
      value.source.tenant_id !== value.tenant_id ||
      value.checkpoint.tenant_id !== value.tenant_id ||
      value.checkpoint.recording_id !== value.source.recording_id ||
      value.checkpoint.source_sha256 !== value.source.source_sha256 ||
      value.checkpoint.source_revision !== value.source.source_revision
    ) {
      context.addIssue({
        code: "custom",
        path: ["checkpoint"],
        message: "Assignment source binding is invalid.",
      });
    }
  });

const finding = z.object({
  title: z.string(),
  explanation: z.string(),
  evidence: z.array(
    z.object({
      segment_id: boundedId,
      quote: z.string(),
      start_ms: z.number(),
      end_ms: z.number(),
    }),
  ),
});
const citation = z.object({ doc: z.string(), sections: z.array(z.string()) });
const report = z.object({
  source_label: z.string(),
  source_sha256: digest,
  summary: z.string(),
  verdict: z.string(),
  review_status: z.string(),
  strengths: z.array(finding),
  missed_opportunities: z.array(finding),
  improvements: z.array(finding),
  objection_analysis: z.array(finding),
  closing_analysis: z.array(finding),
  dimensions: z.array(
    z.object({
      label: z.string(),
      status: z.string(),
      observation: z.string(),
      citations: z.array(citation),
    }),
  ),
  report_sections: z.array(
    z.object({
      number: z.number(),
      title: z.string(),
      required: z.string(),
      citations: z.array(citation),
    }),
  ),
});
const transcriptSegment = z.object({
  id: boundedId,
  speaker_id: z.string(),
  start_ms: z.number().int().nonnegative(),
  end_ms: z.number().int().positive(),
  text: z.string(),
});
const transcript = z.object({
  source_sha256: digest,
  revision: z.string().min(1).max(128),
  timebase_id: z.string().min(1).max(128),
  duration_ms: z.number().int().positive(),
  segments: z.array(transcriptSegment),
});
const loadedResponse = z.object({
  assignment,
  report,
  transcript,
  evidence_spans: z.array(
    transcriptSegment.extend({ checkpoint_id: uuid, span_id: boundedId }),
  ),
  audio_source_url: z.string(),
});
const submission = z.object({
  schema: z.literal("ac.sales-xray.review-feedback/1"),
  id: uuid,
  assignment_id: uuid,
  tenant_id: uuid,
  run_id: uuid,
  reviewer_person_id: uuid,
  author_person_id: uuid,
  lens,
  lane: z.enum(["sales", "signal"]),
  idempotency_key: boundedId,
  request_sha256: digest,
  evidence_refs: z.array(evidenceRef).min(1).max(64),
  confidence,
  feedback: z.string().min(1).max(4000),
  proposed_correction: correction.nullable().optional(),
  created_at_epoch: z.number().int().positive(),
});

export type ReviewAssignmentBinding = z.infer<typeof assignment>;
export type SavedReview = z.infer<typeof submission>;
export type Transcript = z.infer<typeof transcript>;
export type LoadedReviewAssignment = {
  assignment: FormAssignment;
  binding: ReviewAssignmentBinding;
  transcript: Transcript;
};
export type ReviewerAssignmentSummary = ReviewAssignmentBinding;

export class ReviewerApiProblem extends Error {
  readonly status: number;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(status: number, detail: string, requestId: string | null = null) {
    super(detail);
    this.name = "ReviewerApiProblem";
    this.status = status;
    this.requestId = requestId;
    this.retryable = status >= 500 || status === 408 || status === 429;
  }
}

type Fetcher = typeof fetch;
const PRIVATE_REQUEST = {
  cache: "no-store",
  credentials: "same-origin",
  mode: "same-origin",
  redirect: "error",
} as const;

async function parseProblem(response: Response): Promise<ReviewerApiProblem> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // A proxy may return an empty response for a revoked session.
  }
  const candidate =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const detail =
    typeof candidate.detail === "string" && candidate.detail.trim()
      ? candidate.detail
      : "The reviewer request was rejected.";
  return new ReviewerApiProblem(
    response.status,
    detail,
    typeof candidate.request_id === "string" ? candidate.request_id : null,
  );
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>,
  fetcher: Fetcher,
): Promise<T> {
  if (!path.startsWith("/v1/reviewer/") || path.startsWith("//"))
    throw new TypeError(
      "Reviewer requests must use the dedicated same-origin API.",
    );
  const response = await fetcher(path, { ...PRIVATE_REQUEST, ...init });
  if (!response.ok) throw await parseProblem(response);
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }
  return schema.parse(payload);
}

export function reviewerErrorMessage(error: unknown): string {
  if (error instanceof ReviewerApiProblem) {
    if (error.status === 401)
      return "Your reviewer session expired. Request a fresh sign-in link.";
    if (error.status === 403)
      return "This reviewer access is no longer active.";
    if (error.status === 404)
      return "This review is unavailable for the signed-in reviewer.";
    if (error.status === 409)
      return "The assigned call revision changed. Your draft is preserved.";
  }
  return error instanceof Error && !(error instanceof z.ZodError)
    ? error.message
    : "The reviewer service returned an invalid or unavailable response.";
}

function endpoint(assignmentId: string) {
  return `/v1/reviewer/review-assignments/${encodeURIComponent(uuid.parse(assignmentId))}`;
}

function assertBinding(value: ReviewAssignmentBinding, id: string) {
  if (
    value.id !== id ||
    value.source.tenant_id !== value.tenant_id ||
    value.checkpoint.tenant_id !== value.tenant_id ||
    value.checkpoint.recording_id !== value.source.recording_id ||
    value.checkpoint.source_sha256 !== value.source.source_sha256 ||
    value.checkpoint.source_revision !== value.source.source_revision
  )
    throw new Error(
      "The reviewer service returned a different assignment binding.",
    );
  return value;
}

function toFormAssignment(
  bound: ReviewAssignmentBinding,
  reportValue: z.infer<typeof report>,
  spans: z.infer<typeof loadedResponse>["evidence_spans"],
  audio: string,
): FormAssignment {
  const groups = [
    ["Strengths", reportValue.strengths],
    ["Missed opportunities", reportValue.missed_opportunities],
    ["Improvements", reportValue.improvements],
    ["Objection analysis", reportValue.objection_analysis],
    ["Closing analysis", reportValue.closing_analysis],
  ] as const;
  const citations = (items: z.infer<typeof citation>[]) =>
    items.map((item) => `${item.doc}: ${item.sections.join(", ")}`);
  return {
    assignment_id: bound.id,
    recording_id: bound.source.recording_id,
    checkpoint_id: bound.checkpoint.id,
    run_revision: `${bound.run_id} · generation ${bound.run_generation} · ${bound.recipe_revision}`,
    reviewer: {
      person_id: bound.reviewer_person_id,
      display_name: "Assigned reviewer",
    },
    report: {
      title: reportValue.source_label,
      summary: reportValue.summary,
      verdict: reportValue.verdict,
      groups: [
        ...groups.map(([title, findings]) => ({
          title,
          findings: findings.map((item) => ({
            title: item.title,
            explanation: item.explanation,
            evidence: item.evidence.map(
              (ref) =>
                `${ref.segment_id} · ${ref.start_ms / 1000}–${ref.end_ms / 1000}s: ${ref.quote}`,
            ),
          })),
        })),
        {
          title: "Report dimensions",
          kind: "reference" as const,
          findings: reportValue.dimensions.map((item) => ({
            title: `${item.label} · ${item.status.replaceAll("_", " ")}`,
            explanation: item.observation,
            evidence: citations(item.citations),
          })),
        },
        {
          title: "Report framework",
          kind: "reference" as const,
          findings: reportValue.report_sections.map((item) => ({
            title: `${item.number}. ${item.title}`,
            explanation: item.required,
            evidence: citations(item.citations),
          })),
        },
      ],
    },
    clips: spans.map((span) => ({
      checkpoint_id: span.checkpoint_id,
      segment_id: span.span_id,
      start_ms: span.start_ms,
      end_ms: span.end_ms,
      quote: span.text,
      playback_url: audio,
    })),
    allowed_lenses: bound.allowed_lenses,
  };
}

function parseSaved(
  value: unknown,
  loaded: LoadedReviewAssignment,
): SavedReview {
  const item = submission.parse(value);
  const bound = loaded.binding;
  if (
    item.assignment_id !== bound.id ||
    item.tenant_id !== bound.tenant_id ||
    item.run_id !== bound.run_id ||
    item.reviewer_person_id !== bound.reviewer_person_id ||
    item.author_person_id !== bound.reviewer_person_id ||
    item.lane !== (item.lens === "sales" ? "sales" : "signal") ||
    !bound.allowed_lenses.includes(item.lens) ||
    item.evidence_refs.some(
      (ref) =>
        ref.checkpoint_id !== bound.checkpoint.id ||
        !loaded.assignment.clips.some(
          (clip) => clip.segment_id === ref.span_id,
        ),
    ) ||
    new Set(item.evidence_refs.map((ref) => ref.span_id)).size !==
      item.evidence_refs.length ||
    (item.proposed_correction &&
      !(CORRECTION_TARGETS[item.lens] as readonly string[]).includes(
        item.proposed_correction.target_layer,
      ))
  )
    throw new Error(
      "The saved reviewer feedback differs from this assignment.",
    );
  return item;
}

export function createReviewerAssignmentApi(fetcher: Fetcher = fetch) {
  return {
    async queue(
      signal?: AbortSignal,
    ): Promise<{ items: ReviewerAssignmentSummary[]; truncated: boolean }> {
      return requestJson(
        "/v1/reviewer/review-assignments?limit=50",
        { method: "GET", signal },
        z.object({ items: z.array(assignment), truncated: z.boolean() }),
        fetcher,
      );
    },
    async get(
      assignmentId: string,
      signal?: AbortSignal,
    ): Promise<LoadedReviewAssignment> {
      const id = uuid.parse(assignmentId);
      const payload = loadedResponse.parse(
        await requestJson(
          `${endpoint(id)}`,
          { method: "GET", signal },
          loadedResponse,
          fetcher,
        ),
      );
      const bound = assertBinding(payload.assignment, id);
      if (
        payload.audio_source_url !== `${endpoint(id)}/source` ||
        payload.report.source_sha256 !== bound.source.source_sha256 ||
        payload.transcript.source_sha256 !== bound.source.source_sha256 ||
        payload.evidence_spans.some(
          (span) => span.checkpoint_id !== bound.checkpoint.id,
        )
      ) {
        throw new Error(
          "The report, transcript, or audio source is not bound to this assignment.",
        );
      }
      return {
        binding: bound,
        transcript: payload.transcript,
        assignment: toFormAssignment(
          bound,
          payload.report,
          payload.evidence_spans,
          payload.audio_source_url,
        ),
      };
    },
    async history(
      loaded: LoadedReviewAssignment,
      signal?: AbortSignal,
    ): Promise<SavedReview[]> {
      const payload = await requestJson(
        `${endpoint(loaded.binding.id)}/submissions`,
        { method: "GET", signal },
        z.object({ items: z.array(z.unknown()).max(100) }),
        fetcher,
      );
      const items = payload.items.map((item) => parseSaved(item, loaded));
      if (new Set(items.map((item) => item.id)).size !== items.length)
        throw new Error(
          "Saved reviewer feedback contains duplicate submissions.",
        );
      return items;
    },
    async submit(
      loaded: LoadedReviewAssignment,
      draft: ReviewProposalDraft,
      idempotencyKey: string,
    ): Promise<SavedReview> {
      const bound = loaded.binding;
      if (
        !draft.clip ||
        draft.assignment_id !== bound.id ||
        draft.reviewer_id !== bound.reviewer_person_id ||
        draft.clip.checkpoint_id !== bound.checkpoint.id ||
        !loaded.assignment.clips.some(
          (clip) => clip.segment_id === draft.clip?.segment_id,
        )
      )
        throw new Error(
          "Choose one server-provided evidence span before saving.",
        );
      const body = {
        schema: "ac.sales-xray.review-feedback/1" as const,
        idempotency_key: boundedId.parse(idempotencyKey),
        lens: lens.parse(draft.lens),
        evidence_refs: [
          {
            checkpoint_id: draft.clip.checkpoint_id,
            span_id: draft.clip.segment_id,
          },
        ],
        confidence: confidence.parse(draft.confidence),
        feedback: z.string().trim().min(1).max(4000).parse(draft.feedback),
        ...(draft.proposed_correction
          ? { proposed_correction: correction.parse(draft.proposed_correction) }
          : {}),
      };
      const saved = parseSaved(
        await requestJson(
          `${endpoint(bound.id)}/submissions`,
          {
            method: "POST",
            headers: {
              "content-type": "application/json",
              accept: "application/json",
              "idempotency-key": idempotencyKey,
            },
            body: JSON.stringify(body),
          },
          submission,
          fetcher,
        ),
        loaded,
      );
      if (
        saved.idempotency_key !== idempotencyKey ||
        saved.lens !== body.lens ||
        saved.confidence !== body.confidence ||
        saved.feedback !== body.feedback ||
        JSON.stringify(saved.evidence_refs) !==
          JSON.stringify(body.evidence_refs) ||
        JSON.stringify(saved.proposed_correction ?? null) !==
          JSON.stringify(body.proposed_correction ?? null)
      )
        throw new Error(
          "The server receipt differs from your feedback. Retry unchanged feedback to verify it.",
        );
      return saved;
    },
  };
}

export function newReviewerIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto)
    return crypto.randomUUID();
  throw new Error("Secure review submission identity is unavailable.");
}

export async function acceptReviewerInvitation(
  token: string,
  fetcher: Fetcher = fetch,
): Promise<ReviewAssignmentBinding> {
  return requestJson(
    "/v1/reviewer/review-invitations/accept",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({
        schema: "ac.sales-xray.review-invitation-accept/1",
        token,
      }),
    },
    assignment,
    fetcher,
  );
}
