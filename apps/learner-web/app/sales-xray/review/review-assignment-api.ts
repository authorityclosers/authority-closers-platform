import { z } from "zod";
import {
  CORRECTION_TARGETS,
  type ReviewAssignment,
  type ReviewProposalDraft,
} from "@ac/sales-xray-review-ui";
import {
  ApiError,
  createLearnerApi,
  type LearnerFetch,
} from "../../lib/learner-api";

const uuid = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
const id = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/);
const lens = z.enum(["sales", "technical", "ux"]);
const confidence = z.enum(["low", "medium", "high"]);
const evidenceRef = z.object({ checkpoint_id: uuid, span_id: id });
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
  source_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  source_revision: z.number().int().positive(),
});
const assignmentSchema = z.object({
  schema: z.literal("ac.sales-xray.review-assignment/1"),
  id: uuid,
  tenant_id: uuid,
  run_id: uuid,
  run_generation: z.number().int().positive(),
  recipe_revision: z.string().min(1).max(128),
  reviewer_person_id: uuid,
  source,
  checkpoint: source.extend({ id: uuid, stage: z.literal("C2") }),
  allowed_lenses: z
    .array(lens)
    .min(1)
    .max(3)
    .refine((items) => new Set(items).size === items.length),
  state: z.enum(["assigned", "in_progress", "submitted"]),
});
export const reviewAssignmentTransportSchema = assignmentSchema.refine(
  (bound) =>
    bound.tenant_id === bound.source.tenant_id &&
    bound.checkpoint.tenant_id === bound.tenant_id &&
    bound.source.recording_id === bound.checkpoint.recording_id &&
    bound.source.source_revision === bound.checkpoint.source_revision &&
    bound.source.source_sha256 === bound.checkpoint.source_sha256,
  "The accepted assignment differs from its source.",
);
const spanSchema = z
  .object({
    checkpoint_id: uuid,
    span_id: id,
    id,
    start_ms: z.number().int().nonnegative(),
    end_ms: z.number().int().positive(),
    text: z.string(),
  })
  .refine((span) => span.end_ms > span.start_ms && span.id === span.span_id);
const finding = z.object({
  title: z.string(),
  explanation: z.string(),
  evidence: z.array(
    z.object({
      segment_id: id,
      quote: z.string(),
      start_ms: z.number(),
      end_ms: z.number(),
    }),
  ),
});
const citation = z.object({ doc: z.string(), sections: z.array(z.string()) });
const reportSchema = z.object({
  source_label: z.string(),
  source_sha256: z.string(),
  summary: z.string(),
  verdict: z.string(),
  review_status: z.literal("draft_not_dipak_adjudicated"),
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
const responseSchema = z.object({
  assignment: assignmentSchema,
  report: reportSchema,
  evidence_spans: z.array(spanSchema),
  audio_source_url: z.string(),
});
const submissionSchema = z.object({
  schema: z.literal("ac.sales-xray.review-feedback/1"),
  id: uuid,
  assignment_id: uuid,
  tenant_id: uuid,
  run_id: uuid,
  reviewer_person_id: uuid,
  author_person_id: uuid,
  lens,
  lane: z.enum(["sales", "signal"]),
  idempotency_key: id,
  evidence_refs: z.array(evidenceRef).min(1).max(64),
  confidence,
  feedback: z.string().min(1).max(4000),
  proposed_correction: correction.nullable().optional(),
  created_at_epoch: z.number().int().positive(),
});
export type SavedReview = z.infer<typeof submissionSchema>;
export type LoadedReviewAssignment = {
  assignment: ReviewAssignment;
  binding: z.infer<typeof assignmentSchema>;
};
const privateRequest = {
  cache: "no-store",
  mode: "same-origin",
  redirect: "error",
} as const;
function endpoint(assignmentId: string) {
  return `/v1/conversation/review-assignments/${uuid.parse(assignmentId)}`;
}
function parseAssignment(
  payload: unknown,
  assignmentId: string,
): LoadedReviewAssignment {
  const parsed = responseSchema.safeParse(payload);
  if (!parsed.success)
    throw new Error("The review service returned an incomplete assignment.");
  const {
    assignment: bound,
    report,
    evidence_spans: spans,
    audio_source_url: audio,
  } = parsed.data;
  if (bound.id !== assignmentId || audio !== `${endpoint(assignmentId)}/source`)
    throw new Error(
      "The review service returned a different assignment or invalid audio source URL.",
    );
  if (
    bound.tenant_id !== bound.source.tenant_id ||
    bound.checkpoint.tenant_id !== bound.tenant_id ||
    bound.source.recording_id !== bound.checkpoint.recording_id ||
    bound.source.source_revision !== bound.checkpoint.source_revision ||
    bound.source.source_sha256 !== bound.checkpoint.source_sha256 ||
    report.source_sha256 !== bound.source.source_sha256 ||
    spans.some((span) => span.checkpoint_id !== bound.checkpoint.id) ||
    new Set(spans.map((span) => span.span_id)).size !== spans.length
  )
    throw new Error("The report or evidence differs from the assigned source.");
  const groups = [
    ["Strengths", report.strengths],
    ["Missed opportunities", report.missed_opportunities],
    ["Improvements", report.improvements],
    ["Objection analysis", report.objection_analysis],
    ["Closing analysis", report.closing_analysis],
  ] as const;
  const formatCitations = (citations: z.infer<typeof citation>[]) =>
    citations.map((item) => `${item.doc}: ${item.sections.join(", ")}`);
  return {
    binding: bound,
    assignment: {
      assignment_id: bound.id,
      recording_id: bound.source.recording_id,
      checkpoint_id: bound.checkpoint.id,
      run_revision: `${bound.run_id} · generation ${bound.run_generation} · ${bound.recipe_revision}`,
      reviewer: {
        person_id: bound.reviewer_person_id,
        display_name: "Assigned reviewer",
      },
      report: {
        title: report.source_label,
        summary: report.summary,
        verdict: report.verdict,
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
            kind: "reference",
            findings: report.dimensions.map((item) => ({
              title: `${item.label} · ${item.status.replaceAll("_", " ")}`,
              explanation: item.observation,
              evidence: formatCitations(item.citations),
            })),
          },
          {
            title: "Report framework",
            kind: "reference",
            findings: report.report_sections.map((item) => ({
              title: `${item.number}. ${item.title}`,
              explanation: item.required,
              evidence: formatCitations(item.citations),
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
    },
  };
}
function parseSubmission(
  payload: unknown,
  loaded: LoadedReviewAssignment,
): SavedReview {
  const parsed = submissionSchema.safeParse(payload);
  if (!parsed.success)
    throw new Error("The server returned an invalid saved review.");
  const item = parsed.data,
    bound = loaded.binding;
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
    throw new Error("The saved review differs from this assignment.");
  return item;
}
export function createReviewAssignmentApi(fetcher?: LearnerFetch) {
  const api = createLearnerApi(fetcher);
  return {
    async get(
      assignmentId: string,
      signal?: AbortSignal,
    ): Promise<LoadedReviewAssignment> {
      return parseAssignment(
        await api.request<unknown>(endpoint(assignmentId), {
          ...privateRequest,
          signal,
        }),
        assignmentId,
      );
    },
    async history(
      loaded: LoadedReviewAssignment,
      signal?: AbortSignal,
    ): Promise<SavedReview[]> {
      const payload = await api.request<unknown>(
        `${endpoint(loaded.binding.id)}/submissions`,
        { ...privateRequest, signal },
      );
      const list = z
        .object({ items: z.array(z.unknown()).max(100) })
        .safeParse(payload);
      if (!list.success)
        throw new Error("The saved review history could not be read.");
      const items = list.data.items.map((item) =>
        parseSubmission(item, loaded),
      );
      if (new Set(items.map((item) => item.id)).size !== items.length)
        throw new Error(
          "The saved review history contains duplicate submissions.",
        );
      return items;
    },
    async submit(
      loaded: LoadedReviewAssignment,
      draft: ReviewProposalDraft,
      key: string,
    ): Promise<SavedReview> {
      const bound = loaded.binding;
      if (
        draft.assignment_id !== bound.id ||
        draft.reviewer_id !== bound.reviewer_person_id ||
        !draft.clip ||
        draft.clip.checkpoint_id !== bound.checkpoint.id ||
        !loaded.assignment.clips.some(
          (clip) => clip.segment_id === draft.clip?.segment_id,
        )
      )
        throw new Error(
          "Choose one server-provided evidence span before saving.",
        );
      const body = {
        schema: "ac.sales-xray.review-feedback/1",
        idempotency_key: id.parse(key),
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
      const saved = parseSubmission(
        await api.request<unknown>(`${endpoint(bound.id)}/submissions`, {
          ...privateRequest,
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
        loaded,
      );
      if (
        saved.idempotency_key !== key ||
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
export function reviewApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "Your session expired. Sign in again to open this review.";
    if (error.status === 404)
      return "This review is unavailable for the signed-in account and selected Academy.";
    if (error.status === 403)
      return "This review is no longer available. It may have expired or been revoked.";
    if (error.status === 409)
      return "The server could not accept this review version. Your draft is preserved.";
  }
  return error instanceof Error && !(error instanceof z.ZodError)
    ? error.message
    : "The review service could not be reached or returned invalid data.";
}
