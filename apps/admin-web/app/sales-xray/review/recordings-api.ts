import { z } from "zod";

const uuidSchema = z
  .uuid()
  .refine((value) => value === value.toLowerCase(), "UUID must be lowercase.");
const digestSchema = z.string().regex(/^[0-9a-f]{64}$/);
const releaseShaSchema = z.string().regex(/^[0-9a-f]{40}$/);

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

const providerUsageSchema = z.record(
  z.string().min(1),
  z.number().int().nonnegative(),
);

const pricingSnapshotSchema = z
  .object({
    schema: z.literal("ac.sales-xray.pricing-snapshot/1"),
    evidence_release_sha: releaseShaSchema.nullable(),
    provider: z.string().min(1),
    model: z.string().min(1),
    currency: z.literal("INR"),
    usd_to_inr: z.number().positive(),
    source_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    pricing_ref: z.string().min(1),
    evidence_sha256: digestSchema,
    source_url: z.string().url(),
    rate_basis: z.enum([
      "per_hour",
      "per_minute",
      "per_million_tokens",
      "per_million_tokens_with_cache_categories_and_long_context_tier",
    ]),
    usd_per_hour: z.number().nonnegative().nullable(),
    usd_per_minute: z.number().nonnegative().optional(),
    input_usd_per_million_tokens: z.number().nonnegative().nullable(),
    output_usd_per_million_tokens: z.number().nonnegative().nullable(),
    cached_input_usd_per_million_tokens: z.number().nonnegative().optional(),
    cache_write_usd_per_million_tokens: z.number().nonnegative().optional(),
    long_context_threshold_tokens: z.number().int().positive().optional(),
    long_input_usd_per_million_tokens: z.number().nonnegative().optional(),
    long_cached_input_usd_per_million_tokens: z
      .number()
      .nonnegative()
      .optional(),
    long_cache_write_usd_per_million_tokens: z
      .number()
      .nonnegative()
      .optional(),
    long_output_usd_per_million_tokens: z.number().nonnegative().optional(),
    is_billing_rate: z.literal(false),
  })
  .strict()
  .refine(
    (snapshot) =>
      snapshot.evidence_release_sha !== null || snapshot.provider === "openai",
    "Release evidence is required for existing provider snapshots.",
  );

const providerStageSchema = z
  .object({
    stage: z.enum(["C2", "C4", "C5"]),
    run_id: uuidSchema,
    state: z.enum([
      "queued",
      "running",
      "completed",
      "failed",
      "uncertain",
      "cancelled",
    ]),
    provider: z.string().min(1).nullable(),
    model: z.string().min(1).nullable(),
    request_id: z.string().min(1).nullable(),
    usage: providerUsageSchema.nullable(),
    receipt_state: z.enum(["recorded", "not_recorded"]),
    cost_state: z.enum(["reconciliation_required", "settled", "not_settled"]),
    usage_estimate_paise: z.number().int().nonnegative().nullable(),
    usage_estimate_state: z.enum([
      "available",
      "rate_unavailable",
      "usage_unavailable",
    ]),
    usage_estimate_basis: z.string().min(1).nullable(),
    pricing_snapshot: pricingSnapshotSchema.nullable(),
  })
  .strict();

// Runtime diagnostics are an additive observability surface. The API may add
// trace details as the worker learns more about a run; treating those details
// as a closed report contract makes the Admin review page fail before an
// operator can recover the recording. Canonical identity, status, cost and
// report fields below remain strict.
const runtimeTraceSchema = z
  .object({
    submission_id: uuidSchema.nullable().optional(),
    binding_state: z.string().min(1).optional(),
    source_revision: z.number().int().positive().nullable().optional(),
    generation: z.number().int().positive().nullable().optional(),
    scope_complete: z.boolean().optional(),
    plans: z.array(z.unknown()).max(64).optional(),
    tasks: z.array(z.unknown()).max(128).optional(),
    publication: z.record(z.string(), z.unknown()).optional(),
  })
  .passthrough();

const recordingSchema = z
  .object({
    id: uuidSchema,
    // Acquisition and Admin use distinct identifiers. Keep the join visible
    // when present, while remaining compatible with older API releases.
    submission_id: uuidSchema.nullable().optional(),
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
        provider_stages: z.array(providerStageSchema),
      })
      .strict()
      .nullable(),
    runtime_trace: runtimeTraceSchema.optional(),
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
        recovery: z
          .object({
            validation_state: z.enum(["revalidated", "corrected"]),
            provider_calls: z.literal(0),
            review_origin: z.literal("Codex automated proposal"),
          })
          .strict()
          .nullable()
          .optional(),
      })
      .strict(),
    cost: z
      .object({
        currency: z.literal("INR"),
        scope: z.enum(["current_plan", "recording_total"]),
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
        usage_estimate_paise: z.number().int().nonnegative().nullable(),
        usage_estimate_state: z.enum([
          "available",
          "rate_unavailable",
          "partial",
          "usage_unavailable",
          "not_applicable",
        ]),
        usage_estimate_basis: z.string().min(1).nullable(),
        usage_estimate_currency: z.literal("INR").nullable(),
        usage_estimate_fx_usd_to_inr: z.number().positive().nullable(),
        usage_estimate_source_date: z
          .string()
          .regex(/^\d{4}-\d{2}-\d{2}$/)
          .nullable(),
        usage_estimate_is_billing_rate: z.literal(false).nullable(),
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
