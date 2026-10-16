import { z } from "zod";

const value = z.object({
  verdict: z.enum(["agree", "partly", "disagree"]).nullable(),
  score: z.number().int().min(0).max(100).nullable(),
  opinion: z.string(),
});
export const goldRow = z.object({
  id: z.uuid(),
  assignment_id: z.uuid(),
  review_id: z.uuid(),
  reviewer_id: z.uuid(),
  call: z.object({ recording_id: z.uuid() }),
  target: z.string(),
  ai_sha256: z.string(),
  value: value.nullable(),
  supersedes_id: z.uuid().nullable(),
  created_at: z.string(),
  erased: z.boolean(),
  ai_value: z.unknown().optional(),
  reviewer_email: z.string().nullable().optional(),
});
export const goldWorkspace = z.object({
  review_id: z.uuid(),
  version: z.literal("pointer-review/1"),
  review_status: z.literal("ai_draft_not_dipak_reviewed"),
  ai_sha256: z.string(),
  call: z.object({
    recording_id: z.uuid(),
    run_id: z.uuid(),
    source_sha256: z.string(),
    transcript_revision: z.string(),
  }),
  lines: z
    .array(z.object({ target: z.string(), label: z.string(), ai: z.unknown() }))
    .length(29),
  saved: z.array(goldRow),
  history_count: z.number().int(),
  audio_source_url: z.string(),
  transcript: z.object({
    segments: z.array(
      z.object({
        id: z.string(),
        text: z.string(),
        speaker_id: z.string(),
        start_ms: z.number(),
      }),
    ),
  }),
});
export type GoldWorkspace = z.infer<typeof goldWorkspace>;
export type GoldRow = z.infer<typeof goldRow>;
export type GoldValue = z.infer<typeof value>;

export async function goldRequest(path: string, init?: RequestInit) {
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
    ...init,
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail =
      body &&
      typeof body === "object" &&
      "detail" in body &&
      typeof body.detail === "string"
        ? body.detail
        : "This review is unavailable. Try again.";
    throw Object.assign(new Error(detail), { status: response.status });
  }
  return response.json() as Promise<unknown>;
}

export function goldEndpoint(id: string) {
  return `/v1/reviewer/review-assignments/${encodeURIComponent(z.uuid().parse(id))}/gold`;
}

export async function saveGold(
  id: string,
  reviewId: string,
  target: string,
  draft: GoldValue,
  previous: string | null,
  key: string,
) {
  return goldRow.parse(
    await goldRequest(goldEndpoint(id), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify({
        review_id: reviewId,
        target,
        ...draft,
        supersedes_id: previous,
      }),
    }),
  );
}
