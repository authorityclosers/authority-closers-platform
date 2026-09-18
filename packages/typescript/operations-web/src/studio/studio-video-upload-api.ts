import { hashBlobSha256 } from "@ac/ui/blob-sha256";
import { z } from "zod";
import { AdminApiProblem } from "../admin-api";

const uuid = z.uuid();
const size = z.number().int().positive().max(Number.MAX_SAFE_INTEGER);
const lifecycle = z.enum([
  "expected",
  "uploading",
  "processing",
  "ready",
  "failed",
  "retired",
]);
const mime = z.enum(["video/mp4", "video/webm"]);
const checksum = z.string().regex(/^[a-f0-9]{64}$/);
const key = z.string().regex(/^[A-Za-z0-9_-]{1,128}$/);
const instant = z.iso.datetime({ offset: true });
export const studioUploadRequestSchema = z
  .object({
    filename: z
      .string()
      .trim()
      .min(1)
      .max(255)
      .refine(
        (name) =>
          !/[\/\\\p{Cc}\p{Cf}\p{Cs}]/u.test(name) &&
          ![".", ".."].includes(name),
      ),
    content_type: mime,
    content_length: size,
    checksum_sha256: checksum,
  })
  .strict();
const capabilitySchema = z
  .object({
    available: z.boolean(),
    max_source_bytes: size.nullable(),
    accepted_content_types: z.tuple([
      z.literal("video/mp4"),
      z.literal("video/webm"),
    ]),
    reason: z.literal("not_configured").nullable(),
  })
  .strict()
  .refine((item) =>
    item.available
      ? item.max_source_bytes !== null && item.reason === null
      : item.max_source_bytes === null && item.reason === "not_configured",
  );
const intentSchema = z
  .object({
    upload_id: uuid,
    media_id: uuid,
    media_version_id: uuid,
    version_number: z.literal(1),
    state: lifecycle,
    object_key: z.string().min(1).max(512),
    upload_url: z.string().min(1).max(1024),
    upload_headers: z
      .object({
        "content-type": mime,
        "content-length": z.string().regex(/^[1-9][0-9]*$/),
        "x-content-sha256": checksum,
      })
      .strict(),
    expires_at: instant,
    max_bytes: size,
  })
  .strict();
const statusSchema = z
  .object({
    upload_id: uuid,
    asset_id: uuid,
    version_id: uuid,
    label: z.string().min(1).max(255),
    state: lifecycle,
    expires_at: instant,
    declared_bytes: size,
    uploaded_bytes: size.nullable(),
    duration_seconds: z.number().positive().finite().nullable(),
    width: size.nullable(),
    height: size.nullable(),
  })
  .strict()
  .refine((item) => (item.width === null) === (item.height === null))
  .refine(
    (item) =>
      !["processing", "ready"].includes(item.state) ||
      item.uploaded_bytes === item.declared_bytes,
  )
  .refine(
    (item) =>
      item.state !== "ready" ||
      (item.duration_seconds !== null &&
        item.width !== null &&
        item.height !== null),
  );
const completeSchema = z
  .object({
    upload_id: uuid,
    asset_id: uuid,
    version_id: uuid,
    state: lifecycle,
    processing_job_id: uuid.nullable(),
    replayed: z.boolean(),
  })
  .strict();
export type StudioUploadRequest = z.infer<typeof studioUploadRequestSchema>;
export type StudioUploadCapability = z.infer<typeof capabilitySchema>;
export type StudioUploadIntent = z.infer<typeof intentSchema>;
export type StudioUploadStatus = z.infer<typeof statusSchema>;
export const STUDIO_UPLOAD_CHUNK_BYTES = 16 * 1024 * 1024;
type Options = {
  signal?: AbortSignal;
  fetcher?: typeof fetch;
  startOffset?: number;
  onProgress?: (fraction: number) => void;
};
function programPath(programId: string) {
  return `/v1/admin/studio/programs/${uuid.parse(programId)}`;
}
function uploadPath(programId: string, uploadId: string) {
  return `${programPath(programId)}/video-uploads/${uuid.parse(uploadId)}`;
}

async function request<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>,
  options: Options,
) {
  const signal = options.signal
    ? AbortSignal.any([options.signal, AbortSignal.timeout(180_000)])
    : AbortSignal.timeout(180_000);
  const response = await (options.fetcher ?? fetch)(path, {
    ...init,
    signal,
    credentials: "same-origin",
    redirect: "error",
    cache: "no-store",
  });
  if (!response.ok)
    throw new AdminApiProblem({
      status: response.status,
      code: `http_${response.status}`,
      title: "Video request unavailable",
      detail: "The video request could not be confirmed.",
      requestId: null,
    });
  return schema.parse(await response.json());
}

export function loadStudioUploadCapability(
  programId: string,
  options: Options = {},
): Promise<StudioUploadCapability> {
  return request(
    `${programPath(programId)}/video-upload-capability`,
    { method: "GET" },
    capabilitySchema,
    options,
  );
}

export async function createStudioVideoUpload(
  programId: string,
  body: StudioUploadRequest,
  idempotencyKey: string,
  options: Options = {},
): Promise<StudioUploadIntent> {
  const input = studioUploadRequestSchema.parse(body);
  const intent = await request(
    `${programPath(programId)}/video-uploads`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "idempotency-key": key.parse(idempotencyKey),
      },
      body: JSON.stringify(input),
    },
    intentSchema,
    options,
  );
  // Only the exact same-host issued route and immutable source envelope may receive bytes.
  if (
    intent.upload_url !== `${uploadPath(programId, intent.upload_id)}/bytes` ||
    intent.max_bytes < input.content_length ||
    intent.upload_headers["content-type"] !== input.content_type ||
    intent.upload_headers["content-length"] !== String(input.content_length) ||
    intent.upload_headers["x-content-sha256"] !== input.checksum_sha256
  )
    throw new TypeError("The upload receipt did not match this file.");
  return intent;
}

export async function putStudioVideoBytes(
  programId: string,
  intent: StudioUploadIntent,
  source: File,
  body: StudioUploadRequest,
  options: Options = {},
): Promise<void> {
  const path = `${uploadPath(programId, intent.upload_id)}/bytes`;
  if (
    intent.upload_url !== path ||
    source.size !== body.content_length ||
    source.type !== body.content_type ||
    intent.upload_headers["content-length"] !== String(source.size) ||
    intent.upload_headers["content-type"] !== source.type ||
    intent.upload_headers["x-content-sha256"] !== body.checksum_sha256
  )
    throw new TypeError("The upload source changed.");
  const signal = options.signal
    ? AbortSignal.any([options.signal, AbortSignal.timeout(30 * 60_000)])
    : AbortSignal.timeout(30 * 60_000);
  let offset = options.startOffset ?? 0;
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > source.size)
    throw new TypeError("The upload offset changed.");
  while (offset < source.size) {
    const chunk = source.slice(
      offset,
      Math.min(source.size, offset + STUDIO_UPLOAD_CHUNK_BYTES),
    );
    const chunkChecksum = await hashBlobSha256(chunk, { signal });
    const response = await (options.fetcher ?? fetch)(path, {
      method: "PUT",
      body: chunk,
      signal,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: {
        "content-type": body.content_type,
        "x-content-sha256": body.checksum_sha256,
        "x-ac-upload-total": String(source.size),
        "x-ac-upload-offset": String(offset),
        "x-ac-upload-chunk-sha256": chunkChecksum,
      },
    });
    const next = Number(response.headers.get("x-ac-upload-bytes"));
    if (
      response.status !== 204 ||
      !Number.isSafeInteger(next) ||
      next < offset + chunk.size ||
      next > source.size ||
      response.headers.get("x-ac-upload-sha256") !== body.checksum_sha256
    ) {
      throw new AdminApiProblem({
        status: response.ok ? 502 : response.status,
        code: "upload_unconfirmed",
        title: "Upload not confirmed",
        detail: "Retry the same upload to confirm its bytes.",
        requestId: null,
      });
    }
    offset = next;
    options.onProgress?.(offset / source.size);
  }
}

function sameIdentity(
  value: { upload_id: string; asset_id: string; version_id: string },
  intent: StudioUploadIntent,
) {
  if (
    value.upload_id !== intent.upload_id ||
    value.asset_id !== intent.media_id ||
    value.version_id !== intent.media_version_id
  )
    throw new TypeError("The upload context changed.");
}
export async function loadStudioUploadStatus(
  programId: string,
  intent: StudioUploadIntent,
  options: Options = {},
): Promise<StudioUploadStatus> {
  const result = await request(
    uploadPath(programId, intent.upload_id),
    { method: "GET" },
    statusSchema,
    options,
  );
  sameIdentity(result, intent);
  if (result.declared_bytes !== Number(intent.upload_headers["content-length"]))
    throw new TypeError("The uploaded file changed.");
  return result;
}
export async function completeStudioVideoUpload(
  programId: string,
  intent: StudioUploadIntent,
  idempotencyKey: string,
  options: Options = {},
) {
  const result = await request(
    `${uploadPath(programId, intent.upload_id)}/complete`,
    {
      method: "POST",
      headers: { "idempotency-key": key.parse(idempotencyKey) },
    },
    completeSchema,
    options,
  );
  sameIdentity(result, intent);
  return result;
}
