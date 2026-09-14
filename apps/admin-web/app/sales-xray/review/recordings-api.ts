import { z } from "zod";

const uuidSchema = z
  .uuid()
  .refine((value) => value === value.toLowerCase(), "UUID must be lowercase.");
const digestSchema = z.string().regex(/^[0-9a-f]{64}$/);

const ownerSchema = z
  .object({
    kind: z.enum(["learner", "guest"]),
    label: z.string().min(1),
    person_id: uuidSchema.nullable(),
    display_name: z.string().nullable(),
    email: z.string().nullable(),
    claimed: z.boolean(),
  })
  .strict();

const recordingSchema = z
  .object({
    id: uuidSchema,
    owner: ownerSchema,
    uploaded_at: z.string().datetime({ offset: true }),
    recording_state: z.enum(["awaiting_upload", "ready", "deleting"]),
    source: z
      .object({
        bytes: z.number().int().positive(),
        content_type: z.string().min(1),
        sha256: digestSchema,
        revision: z.number().int().positive(),
      })
      .strict(),
    duration: z
      .object({
        milliseconds: z.number().int().positive().nullable(),
        seconds: z.number().positive().nullable(),
        source: z
          .enum(["native_measurement", "acquisition_allowance"])
          .nullable(),
      })
      .strict(),
    status: z.enum([
      "awaiting_upload",
      "ready",
      "deleting",
      "processing",
      "queued",
      "running",
      "completed",
      "cancelled",
      "failed",
      "quoted",
      "active",
      "held",
    ]),
    latest_run: z
      .object({
        id: uuidSchema,
        state: z.enum([
          "queued",
          "running",
          "completed",
          "cancelled",
          "failed",
        ]),
        generation: z.number().int().positive(),
        recipe_revision: z.string().min(1),
        created_at: z.string().datetime({ offset: true }),
        completed_at: z.string().datetime({ offset: true }).nullable(),
      })
      .strict()
      .nullable(),
    processing_plan: z
      .object({
        id: uuidSchema,
        state: z.enum(["quoted", "active", "completed", "held", "cancelled"]),
      })
      .strict()
      .nullable(),
    report: z
      .object({
        available: z.boolean(),
        id: uuidSchema.nullable(),
        run_id: uuidSchema.nullable(),
        review_eligible: z.boolean(),
        invite_eligible: z.boolean(),
      })
      .strict(),
    cost: z
      .object({
        currency: z.literal("INR"),
        reservation_paise: z.number().int().nonnegative().nullable(),
        estimate_paise: z.number().int().nonnegative().nullable(),
        actual_paise: z.number().int().nonnegative().nullable(),
        reservation_state: z
          .enum([
            "reserved",
            "in_flight",
            "uncertain",
            "settled",
            "released",
            "reconciliation_required",
          ])
          .nullable(),
        actual_state: z.enum([
          "settled",
          "reconciliation_required",
          "not_settled",
        ]),
      })
      .strict(),
  })
  .strict();

const recordingsPayloadSchema = z
  .object({
    items: z.array(recordingSchema),
    next_cursor: z.string().min(1).nullable(),
  })
  .strict();

export type AdminRecording = z.infer<typeof recordingSchema>;
export type AdminRecordingsPayload = z.infer<typeof recordingsPayloadSchema>;

type Fetcher = typeof fetch;

export async function loadAdminRecordings({
  limit = 25,
  cursor,
  search,
  fetcher = fetch,
  signal,
}: {
  limit?: number;
  cursor?: string | null;
  search?: string;
  fetcher?: Fetcher;
  signal?: AbortSignal;
} = {}): Promise<AdminRecordingsPayload> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new TypeError("limit must be between 1 and 50.");
  }
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  if (search?.trim()) params.set("q", search.trim());
  const response = await fetcher(
    `/v1/admin/conversation/recordings?${params}`,
    {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
      mode: "same-origin",
      redirect: "error",
      headers: { accept: "application/json" },
      signal,
    },
  );
  if (!response.ok) {
    let message = "The recording inventory could not be loaded.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail.trim())
        message = body.detail;
    } catch {
      // Preserve the bounded fallback message for non-JSON failures.
    }
    const error = new Error(message) as Error & { retryable?: boolean };
    error.retryable =
      response.status >= 500 ||
      response.status === 408 ||
      response.status === 429;
    throw error;
  }
  return recordingsPayloadSchema.parse(await response.json());
}
