import { z } from "zod";
import { AdminApiProblem } from "../admin-api";

const identifier = z.uuid();
const label = z
  .string()
  .min(1)
  .max(255)
  .refine(
    (value) => value.trim().length > 0 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value),
  );
const positiveInteger = z.number().int().positive();
const positiveNumber = z.number().finite().positive();

export const studioVideoChoiceSchema = z
  .object({
    asset_id: identifier,
    version_id: identifier,
    version_number: positiveInteger,
    label,
    state: z.literal("ready"),
    actual_bytes: positiveInteger.nullable(),
    duration_seconds: positiveNumber.nullable(),
    width: positiveInteger.nullable(),
    height: positiveInteger.nullable(),
  })
  .strict()
  .refine((item) => (item.width === null) === (item.height === null));

const pageSchema = z
  .object({
    items: z.array(studioVideoChoiceSchema).max(24),
    next_cursor: identifier.nullable(),
  })
  .strict()
  .refine(
    (page) =>
      new Set(page.items.map((item) => item.asset_id)).size ===
        page.items.length &&
      (page.next_cursor === null ||
        page.next_cursor === page.items.at(-1)?.asset_id),
  );

const bindingSchema = z
  .object({
    binding_id: identifier,
    asset_id: identifier,
    version_id: identifier,
    label,
    state: z.literal("approved"),
  })
  .strict();

const currentSchema = z
  .object({
    activity_id: identifier,
    version_status: z.string().min(1).max(32),
    binding: bindingSchema.nullable(),
  })
  .strict();

export const studioVideoSelectionSchema = z
  .object({
    asset_id: identifier,
    version_id: identifier,
    expected_binding_id: identifier.nullable(),
    approval_reference: z
      .string()
      .min(1)
      .max(200)
      .refine(
        (value) =>
          value.trim().length > 0 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value),
      ),
  })
  .strict();

const receiptSchema = z
  .object({
    binding_id: identifier,
    asset_id: identifier,
    version_id: identifier,
    state: z.enum(["approved", "superseded", "revoked"]),
    replayed: z.boolean(),
  })
  .strict();

export type StudioVideoChoice = z.infer<typeof studioVideoChoiceSchema>;
export type StudioVideoPage = z.infer<typeof pageSchema>;
export type StudioActivityVideo = z.infer<typeof currentSchema>;
export type StudioVideoSelection = z.infer<typeof studioVideoSelectionSchema>;
export type StudioVideoReceipt = z.infer<typeof receiptSchema>;

type ReadOptions = { signal?: AbortSignal; fetcher?: typeof fetch };

function programPath(programId: string) {
  return `/v1/admin/studio/programs/${identifier.parse(programId)}`;
}

async function request<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>,
  fetcher = fetch,
) {
  const response = await fetcher(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const candidate = z
      .object({
        code: z.string().max(128).optional(),
        title: z.string().max(200).optional(),
        detail: z.string().max(2000).optional(),
        request_id: z.string().max(200).nullable().optional(),
      })
      .safeParse(body);
    const problem = candidate.success ? candidate.data : {};
    throw new AdminApiProblem({
      status: response.status,
      code: problem.code || `http_${response.status}`,
      title: problem.title || "Video request rejected",
      detail: problem.detail || "The video request was not accepted.",
      requestId: problem.request_id ?? null,
    });
  }
  return schema.parse(body);
}

export async function loadStudioVideos({
  programId,
  after = null,
  signal,
  fetcher,
}: ReadOptions & {
  programId: string;
  after?: string | null;
}): Promise<StudioVideoPage> {
  const cursor = after === null ? "" : `&after=${identifier.parse(after)}`;
  const page = await request(
    `${programPath(programId)}/videos?limit=24${cursor}`,
    { method: "GET", signal, headers: { accept: "application/json" } },
    pageSchema,
    fetcher,
  );
  // A malformed/nonadvancing cursor must not create an endless picker loop.
  if (
    after &&
    page.items.some(
      (item) => item.asset_id.toLowerCase() <= after.toLowerCase(),
    )
  ) {
    throw new TypeError("The video page did not advance.");
  }
  return page;
}

export async function loadStudioActivityVideo({
  programId,
  activityId,
  signal,
  fetcher,
}: ReadOptions & {
  programId: string;
  activityId: string;
}): Promise<StudioActivityVideo> {
  const result = await request(
    `${programPath(programId)}/activities/${identifier.parse(activityId)}/video`,
    { method: "GET", signal, headers: { accept: "application/json" } },
    currentSchema,
    fetcher,
  );
  if (result.activity_id !== activityId)
    throw new TypeError("The lesson context changed.");
  return result;
}

export async function saveStudioActivityVideo({
  programId,
  activityId,
  selection,
  idempotencyKey,
  signal,
  fetcher,
}: ReadOptions & {
  programId: string;
  activityId: string;
  selection: StudioVideoSelection;
  idempotencyKey: string;
}): Promise<StudioVideoReceipt> {
  const body = studioVideoSelectionSchema.parse(selection);
  const key = z
    .string()
    .min(1)
    .max(128)
    .regex(/^[A-Za-z0-9_-]+$/)
    .parse(idempotencyKey);
  const result = await request(
    `${programPath(programId)}/activities/${identifier.parse(activityId)}/video`,
    {
      method: "POST",
      signal,
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "idempotency-key": key,
      },
      body: JSON.stringify(body),
    },
    receiptSchema,
    fetcher,
  );
  if (
    result.asset_id !== body.asset_id ||
    result.version_id !== body.version_id
  ) {
    throw new TypeError("The video receipt did not match the request.");
  }
  return result;
}
