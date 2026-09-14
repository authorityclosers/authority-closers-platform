import { z } from "zod";

const uuidSchema = z
  .uuid()
  .refine((value) => value === value.toLowerCase(), "UUID must be lowercase.");
const digestSchema = z.string().regex(/^[0-9a-f]{64}$/);

const evidenceSchema = z
  .object({
    segment_id: z.string().min(1),
    quote: z.string().min(1),
    start_ms: z.number().int().nonnegative(),
    end_ms: z.number().int().positive(),
  })
  .strict();

const findingSchema = z
  .object({
    title: z.string().min(1),
    explanation: z.string().min(1),
    evidence: z.array(evidenceSchema),
  })
  .strict();

const reportSchema = z
  .object({
    summary: z.string().min(1),
    strengths: z.array(findingSchema),
    missed_opportunities: z.array(findingSchema),
    improvements: z.array(findingSchema),
    objection_analysis: z.array(findingSchema),
    closing_analysis: z.array(findingSchema),
    verdict: z.string().min(1),
    review_status: z.literal("draft_not_dipak_adjudicated"),
    source_label: z.string().min(1),
    source_sha256: digestSchema,
    transcript_revision: z.string().min(1),
    dimensions: z.array(
      z
        .object({
          dimension_id: z.string().min(1),
          label: z.string().min(1),
          status: z.enum([
            "observed",
            "insufficient_evidence",
            "not_applicable",
            "conflicted",
            "unknown",
          ]),
          observation: z.string().min(1),
        })
        .passthrough(),
    ),
    report_sections: z.array(
      z
        .object({
          number: z.number().int().positive(),
          title: z.string().min(1),
          required: z.string().min(1),
        })
        .passthrough(),
    ),
  })
  .passthrough();

const adminReportSchema = z
  .object({
    id: uuidSchema,
    run_id: uuidSchema,
    recording_id: uuidSchema,
    tenant_id: uuidSchema,
    source: z
      .object({
        sha256: digestSchema,
        revision: z.number().int().positive(),
        retention_until: z.string().datetime({ offset: true }),
      })
      .strict(),
    report: reportSchema,
    message: z.string().min(1),
  })
  .strict();

export type AdminReport = z.infer<typeof adminReportSchema>;

type Fetcher = typeof fetch;

function assertRunId(value: string): string {
  const parsed = uuidSchema.safeParse(value);
  if (!parsed.success) throw new TypeError("runId must be a canonical UUID.");
  return parsed.data;
}

export class AdminReportApiError extends Error {
  readonly status: number;
  readonly retryable: boolean;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AdminReportApiError";
    this.status = status;
    this.retryable = status >= 500 || status === 408 || status === 429;
  }
}

export async function loadAdminReport({
  runId,
  fetcher = fetch,
  signal,
}: {
  runId: string;
  fetcher?: Fetcher;
  signal?: AbortSignal;
}): Promise<AdminReport> {
  const id = encodeURIComponent(assertRunId(runId));
  const response = await fetcher(`/v1/admin/conversation/runs/${id}/report`, {
    method: "GET",
    cache: "no-store",
    credentials: "same-origin",
    mode: "same-origin",
    redirect: "error",
    headers: { accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    let message = "The report could not be opened.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail.trim()) {
        message = body.detail;
      }
    } catch {
      // Keep the bounded fallback for non-JSON failures.
    }
    throw new AdminReportApiError(response.status, message);
  }
  return adminReportSchema.parse(await response.json());
}
