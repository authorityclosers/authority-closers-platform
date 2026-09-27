import {
  ApiError,
  type LearnerApi,
  type AvatarCropMetadata,
  type ProfileAvatarResponse,
} from "./learner-api";
import { isLocalSandboxAvatarUploadUrl } from "./local-avatar-url";
import { hashBlobSha256, BLOB_HASH_CHUNK_BYTES } from "@ac/ui/blob-sha256";

export const AVATAR_ACCEPTED_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

export type AvatarAcceptedMimeType =
  (typeof AVATAR_ACCEPTED_MIME_TYPES)[number];

export type AvatarCrop = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

export type AvatarImageDimensions = {
  width: number;
  height: number;
};

export type AvatarPresentation = {
  assetId?: string;
  versionId?: string;
  deliveryUrl: string;
  alt: string;
  revision: string;
};

export type AvatarUploadInput = {
  file: File;
  crop: AvatarCrop;
  sourceDimensions: AvatarImageDimensions;
  displayName?: string;
  currentAvatar?: AvatarPresentation | null;
  profileRevision?: string | number | null;
};

export type AvatarUploadResult =
  | {
      status: "processing";
      operationId: string;
      stage: "validating" | "processing" | "ready";
    }
  | { status: "success"; avatar: AvatarPresentation }
  | { status: "retryable_error"; message: string }
  | { status: "terminal_error"; message: string }
  | {
      status: "not_available";
      reason: "avatar_upload_not_integrated";
    };

export type AvatarUploadTerminalResult = Exclude<
  AvatarUploadResult,
  { status: "processing" }
>;

export interface AvatarUploadPort {
  upload(
    input: AvatarUploadInput,
    signal?: AbortSignal,
  ): Promise<AvatarUploadResult>;
  /**
   * The adapter owns provider-specific polling/subscription details. The UI
   * only consumes the final server-confirmed result when one is available.
   */
  awaitProcessing?: (
    operationId: string,
    signal?: AbortSignal,
    displayName?: string,
  ) => Promise<AvatarUploadTerminalResult>;
  /** Compatibility status probe for the existing crop dialog contract. */
  getStatus?: (
    operationId: string,
    signal?: AbortSignal,
    displayName?: string,
  ) => Promise<AvatarUploadResult>;
}

export type AvatarFileValidation =
  | { ok: true; mimeType: AvatarAcceptedMimeType }
  | {
      ok: false;
      code:
        | "missing"
        | "unsupported_type"
        | "invalid_size"
        | "invalid_dimensions";
      message: string;
    };

export function validateAvatarFile(
  file: Pick<File, "type" | "size"> | null | undefined,
  dimensions?: { width: number; height: number },
): AvatarFileValidation {
  if (!file) {
    return {
      ok: false,
      code: "missing",
      message: "Choose an image to preview your avatar.",
    };
  }

  if (!Number.isFinite(file.size) || file.size <= 0) {
    return {
      ok: false,
      code: "invalid_size",
      message: "This image has no readable file data. Choose another image.",
    };
  }

  if (
    !AVATAR_ACCEPTED_MIME_TYPES.includes(file.type as AvatarAcceptedMimeType)
  ) {
    return {
      ok: false,
      code: "unsupported_type",
      message: "Use a JPEG, PNG, or WebP image.",
    };
  }

  if (
    dimensions &&
    (!Number.isInteger(dimensions.width) ||
      !Number.isInteger(dimensions.height) ||
      dimensions.width <= 0 ||
      dimensions.height <= 0)
  ) {
    return {
      ok: false,
      code: "invalid_dimensions",
      message: "The image dimensions could not be read. Choose another image.",
    };
  }

  return { ok: true, mimeType: file.type as AvatarAcceptedMimeType };
}

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function validImageDimensions(
  dimensions: AvatarImageDimensions | null | undefined,
): dimensions is AvatarImageDimensions {
  return Boolean(
    dimensions &&
      Number.isInteger(dimensions.width) &&
      Number.isInteger(dimensions.height) &&
      dimensions.width > 0 &&
      dimensions.height > 0,
  );
}

/**
 * The crop viewport is square, matching the preview's object-fit: cover box.
 * These are the visible source fractions at neutral scale, before pan/zoom.
 */
export function coverCropExtent(
  dimensions: AvatarImageDimensions,
): Pick<AvatarCropMetadata, "width" | "height"> {
  if (!validImageDimensions(dimensions)) {
    return { width: 1, height: 1 };
  }
  const aspect = dimensions.width / dimensions.height;
  return aspect >= 1
    ? { width: 1 / aspect, height: 1 }
    : { width: 1, height: aspect };
}

function maxSafePanPercent(baseExtent: number, scale: number): number {
  return Math.max(0, ((scale - baseExtent) / baseExtent) * 50);
}

export function clampAvatarCrop(
  crop: AvatarCrop,
  sourceDimensions?: AvatarImageDimensions,
): AvatarCrop {
  const scale = Math.min(2, Math.max(1, finiteOr(crop.scale, 1)));
  const defaultPan = 25;
  const extent = validImageDimensions(sourceDimensions)
    ? coverCropExtent(sourceDimensions)
    : { width: 1, height: 1 };
  const maxPanX = validImageDimensions(sourceDimensions)
    ? Math.min(defaultPan, maxSafePanPercent(extent.width, scale))
    : defaultPan;
  const maxPanY = validImageDimensions(sourceDimensions)
    ? Math.min(defaultPan, maxSafePanPercent(extent.height, scale))
    : defaultPan;
  return {
    scale,
    offsetX: Math.min(maxPanX, Math.max(-maxPanX, finiteOr(crop.offsetX, 0))),
    offsetY: Math.min(maxPanY, Math.max(-maxPanY, finiteOr(crop.offsetY, 0))),
  };
}

/**
 * Convert the direct-manipulation preview to the normalized source crop
 * accepted by the server. The preview is a square object-fit: cover box:
 * the neutral crop removes the longer source axis, then scale and translation
 * are applied around the source center. The UI never sends CSS transforms as
 * canonical media data.
 */
export function toAvatarCropMetadata(
  crop: AvatarCrop,
  sourceDimensions: AvatarImageDimensions = { width: 1, height: 1 },
): AvatarCropMetadata {
  const extent = coverCropExtent(sourceDimensions);
  const bounded = clampAvatarCrop(crop, sourceDimensions);
  const width = extent.width / bounded.scale;
  const height = extent.height / bounded.scale;
  const x =
    0.5 - width / 2 - (bounded.offsetX / 100) * (extent.width / bounded.scale);
  const y =
    0.5 -
    height / 2 -
    (bounded.offsetY / 100) * (extent.height / bounded.scale);
  return {
    x: Math.min(1 - width, Math.max(0, x)),
    y: Math.min(1 - height, Math.max(0, y)),
    width,
    height,
    rotation_degrees: 0,
  };
}

function avatarFromResponse(
  response: ProfileAvatarResponse,
  displayName: string,
): AvatarPresentation | null {
  const avatar = response.avatar;
  if (
    !avatar ||
    avatar.state !== "ready" ||
    !avatar.delivery_url ||
    !avatar.version_id ||
    !avatar.asset_id
  ) {
    return null;
  }
  const accessibleName = displayName.trim() || "Learner";
  return {
    assetId: avatar.asset_id,
    versionId: avatar.version_id,
    deliveryUrl: avatar.delivery_url,
    alt: `${accessibleName}'s profile photo`,
    revision: String(avatar.version_number),
  };
}

function publicUploadFailure(error: unknown): AvatarUploadTerminalResult {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) {
      return {
        status: "terminal_error",
        message:
          "Your profile session is no longer authorized. Sign in again before changing your avatar.",
      };
    }
    if ([400, 404, 409, 413, 422].includes(error.status)) {
      return {
        status: "terminal_error",
        message:
          "This image could not be accepted. Your current avatar is unchanged.",
      };
    }
    if ([429, 500, 502, 503, 504].includes(error.status)) {
      return {
        status: "retryable_error",
        message:
          "Avatar storage is temporarily unavailable. Your current avatar is unchanged; try again shortly.",
      };
    }
  }
  return {
    status: "retryable_error",
    message:
      "The avatar service could not finish this request. Your current avatar is unchanged.",
  };
}

class DirectUploadError extends Error {
  readonly status: number;

  constructor(status: number) {
    super("The private upload target rejected the image.");
    this.name = "DirectUploadError";
    this.status = status;
  }
}

function publicDirectUploadFailure(error: unknown): AvatarUploadTerminalResult {
  if (
    error instanceof DirectUploadError &&
    [400, 401, 403, 404, 409, 413, 422].includes(error.status)
  ) {
    return {
      status: "terminal_error",
      message:
        "This image could not be accepted by the profile service. Your current avatar is unchanged.",
    };
  }
  return {
    status: "retryable_error",
    message:
      "The image upload could not reach the profile service. Your current avatar is unchanged; try again.",
  };
}

const AVATAR_API_TIMEOUT_MS = 15_000;
const AVATAR_PUT_TIMEOUT_MS = 30_000;
const AVATAR_PROCESSING_TIMEOUT_MS = 45_000;
const AVATAR_STATUS_TIMEOUT_MS = 8_000;
const AVATAR_STATUS_MAX_ATTEMPTS = 12;
const AVATAR_STATUS_INITIAL_DELAY_MS = 750;
const AVATAR_STATUS_MAX_DELAY_MS = 5_000;
export const AVATAR_HASH_CHUNK_BYTES = BLOB_HASH_CHUNK_BYTES;
const FILESYSTEM_AVATAR_UPLOAD_PREFIX = "/v1/media/filesystem-avatar-upload/";
const FILESYSTEM_AVATAR_OBJECT_KEY =
  /^tenants\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/media\/avatar\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/original$/;
const MEDIA_TOKEN = /^AC-MEDIA\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/;

class AvatarTimeoutError extends Error {
  constructor() {
    super("The avatar request timed out.");
    this.name = "AvatarTimeoutError";
  }
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

async function withTimeout<T>(
  parentSignal: AbortSignal | undefined,
  timeoutMs: number,
  action: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const onParentAbort = () => controller.abort();
  parentSignal?.addEventListener("abort", onParentAbort, { once: true });
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  let rejectCancellation: ((reason?: unknown) => void) | undefined;
  const cancellation = new Promise<T>((_, reject) => {
    rejectCancellation = reject;
  });
  const onControllerAbort = () => {
    rejectCancellation?.(timedOut ? new AvatarTimeoutError() : abortError());
  };
  controller.signal.addEventListener("abort", onControllerAbort, {
    once: true,
  });
  try {
    throwIfAborted(parentSignal);
    const result = await Promise.race([
      action(controller.signal),
      cancellation,
    ]);
    throwIfAborted(parentSignal);
    if (timedOut) throw new AvatarTimeoutError();
    return result;
  } catch (error) {
    if (parentSignal?.aborted) throw error;
    if (timedOut || controller.signal.aborted) throw new AvatarTimeoutError();
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    parentSignal?.removeEventListener("abort", onParentAbort);
    controller.signal.removeEventListener("abort", onControllerAbort);
  }
}

async function checksumSha256(
  file: File,
  signal?: AbortSignal,
): Promise<string | undefined> {
  if (typeof file.slice !== "function") return undefined;
  try {
    return await hashBlobSha256(file, { signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    return undefined;
  }
}

type AvatarDirectUploadIntent = {
  upload_url: string;
  object_key: string;
  upload_headers: Record<string, string>;
};

type AvatarDirectUploadOptions = Pick<
  RequestInit,
  "headers" | "credentials" | "mode" | "cache" | "redirect" | "referrerPolicy"
>;

function browserSafeUploadHeaders(
  headers: Record<string, string>,
): Record<string, string> {
  const safe: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers)) {
    const normalized = name.toLowerCase();
    if (
      normalized === "content-length" ||
      normalized === "origin" ||
      normalized === "cookie" ||
      normalized === "host"
    ) {
      continue;
    }
    safe[name] = value;
  }
  return safe;
}

function avatarDirectUploadOptions(
  intent: AvatarDirectUploadIntent,
  file: File,
  contentType: AvatarAcceptedMimeType,
  checksum: string,
  browserOrigin: string | null = typeof window === "undefined"
    ? null
    : window.location.origin,
): AvatarDirectUploadOptions | null {
  let uploadUrl: URL;
  try {
    uploadUrl = new URL(intent.upload_url);
  } catch {
    return null;
  }

  if (uploadUrl.pathname.startsWith(FILESYSTEM_AVATAR_UPLOAD_PREFIX)) {
    const normalized = new Map<string, string>();
    for (const [name, value] of Object.entries(intent.upload_headers)) {
      const key = name.toLowerCase();
      if (normalized.has(key)) return null;
      normalized.set(key, value);
    }
    const tokenEntries = Array.from(uploadUrl.searchParams.entries());
    const encodedKey = intent.object_key.replaceAll("/", "%2F");
    if (
      !browserOrigin ||
      uploadUrl.protocol !== "https:" ||
      uploadUrl.origin !== browserOrigin ||
      uploadUrl.username ||
      uploadUrl.password ||
      uploadUrl.hash ||
      !FILESYSTEM_AVATAR_OBJECT_KEY.test(intent.object_key) ||
      uploadUrl.pathname !==
        `${FILESYSTEM_AVATAR_UPLOAD_PREFIX}${encodedKey}` ||
      tokenEntries.length !== 1 ||
      tokenEntries[0]?.[0] !== "token" ||
      uploadUrl.search !== `?token=${tokenEntries[0]?.[1]}` ||
      !MEDIA_TOKEN.test(tokenEntries[0]?.[1] ?? "") ||
      normalized.size !== 3 ||
      normalized.get("content-type") !== contentType ||
      normalized.get("content-length") !== String(file.size) ||
      normalized.get("x-content-sha256") !== checksum
    ) {
      return null;
    }
    return {
      headers: {
        "content-type": contentType,
        "x-content-sha256": checksum,
      },
      credentials: "same-origin",
      mode: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
    };
  }

  const localSandbox = isLocalSandboxAvatarUploadUrl(uploadUrl, browserOrigin);
  if (
    (!localSandbox && uploadUrl.protocol !== "https:") ||
    uploadUrl.username ||
    uploadUrl.password ||
    uploadUrl.hash
  ) {
    return null;
  }
  return {
    headers: browserSafeUploadHeaders(intent.upload_headers),
    credentials: localSandbox ? "same-origin" : "omit",
    ...(localSandbox ? { mode: "same-origin" as const } : {}),
    cache: "no-store",
    redirect: "error",
    referrerPolicy: "no-referrer",
  };
}

type AvatarUploadApi = Pick<
  LearnerApi,
  "createProfileAvatarUpload" | "completeProfileAvatarUpload" | "profileAvatar"
>;

function asProcessing(
  operationId: string,
  response: ProfileAvatarResponse,
): AvatarUploadResult {
  const pending = response.pending;
  return {
    status: "processing",
    operationId,
    stage:
      pending?.state === "uploading"
        ? "validating"
        : pending?.state === "ready"
          ? "ready"
          : "processing",
  };
}

function waitFor(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(abortError());
  }
  return new Promise((resolve, reject) => {
    const timeout = globalThis.setTimeout(finish, ms);
    function abort() {
      globalThis.clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
      reject(abortError());
    }
    function finish() {
      signal?.removeEventListener("abort", abort);
      resolve();
    }
    signal?.addEventListener("abort", abort, { once: true });
  });
}

function isTerminalApiError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    [400, 401, 403, 404, 409, 413, 422].includes(error.status)
  );
}

export function createApiAvatarUploadPort(
  api: AvatarUploadApi,
): AvatarUploadPort {
  const port: AvatarUploadPort = {
    async upload(input, signal) {
      throwIfAborted(signal);
      const validation = validateAvatarFile(input.file, input.sourceDimensions);
      if (!validation.ok) {
        return { status: "terminal_error", message: validation.message };
      }
      if (!validImageDimensions(input.sourceDimensions)) {
        return {
          status: "terminal_error",
          message:
            "The image dimensions could not be confirmed. Your current avatar is unchanged.",
        };
      }
      const crop = toAvatarCropMetadata(input.crop, input.sourceDimensions);
      try {
        const checksum = await checksumSha256(input.file, signal);
        if (!checksum) {
          return {
            status: "terminal_error",
            message:
              "The image could not be verified safely. Your current avatar is unchanged.",
          };
        }
        const intent = await withTimeout(
          signal,
          AVATAR_API_TIMEOUT_MS,
          (requestSignal) =>
            api.createProfileAvatarUpload(
              {
                filename: input.file.name || "avatar",
                content_type: validation.mimeType,
                content_length: input.file.size,
                checksum_sha256: checksum,
                asset_id: input.currentAvatar?.assetId ?? null,
                supersedes_version_id: input.currentAvatar?.versionId ?? null,
                crop,
              },
              requestSignal,
            ),
        );
        const expiresAt = new Date(intent.expires_at).getTime();
        if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
          return {
            status: "retryable_error",
            message:
              "The avatar upload window expired before it started. Your current avatar is unchanged; try again.",
          };
        }
        const uploadOptions = avatarDirectUploadOptions(
          intent,
          input.file,
          validation.mimeType,
          checksum,
        );
        if (!uploadOptions) {
          return {
            status: "terminal_error",
            message:
              "The profile service returned an invalid upload target. Your current avatar is unchanged.",
          };
        }

        let uploadResponse: Response;
        try {
          uploadResponse = await withTimeout(
            signal,
            AVATAR_PUT_TIMEOUT_MS,
            (requestSignal) =>
              fetch(intent.upload_url, {
                method: "PUT",
                ...uploadOptions,
                body: input.file,
                signal: requestSignal,
              }),
          );
        } catch (error) {
          if (signal?.aborted) throw error;
          return publicDirectUploadFailure(error);
        }
        if (!uploadResponse.ok) {
          return publicDirectUploadFailure(
            new DirectUploadError(uploadResponse.status),
          );
        }

        const completed = await withTimeout(
          signal,
          AVATAR_API_TIMEOUT_MS,
          (requestSignal) =>
            api.completeProfileAvatarUpload(
              intent.upload_id,
              { actual_bytes: input.file.size, checksum_sha256: checksum },
              requestSignal,
            ),
        );
        if (completed.state === "failed") {
          return {
            status: "terminal_error",
            message:
              "The profile service rejected this image. Your current avatar is unchanged.",
          };
        }
        const profile = await withTimeout(
          signal,
          AVATAR_API_TIMEOUT_MS,
          (requestSignal) => api.profileAvatar({ signal: requestSignal }),
        );
        const avatar = avatarFromResponse(
          profile,
          input.displayName || "Learner",
        );
        if (avatar && avatar.versionId === intent.media_version_id) {
          return { status: "success", avatar };
        }
        return asProcessing(intent.media_version_id, profile);
      } catch (error) {
        if (signal?.aborted) throw error;
        return publicUploadFailure(error);
      }
    },

    async awaitProcessing(operationId, signal, displayName = "Learner") {
      const deadline = Date.now() + AVATAR_PROCESSING_TIMEOUT_MS;
      let delay = AVATAR_STATUS_INITIAL_DELAY_MS;
      let lastRetryable: AvatarUploadTerminalResult = {
        status: "retryable_error",
        message:
          "Avatar processing is taking longer than expected. Your current avatar is unchanged; reopen the editor to check again.",
      };

      for (
        let attempt = 0;
        attempt < AVATAR_STATUS_MAX_ATTEMPTS;
        attempt += 1
      ) {
        throwIfAborted(signal);
        let profile: ProfileAvatarResponse;
        try {
          profile = await withTimeout(
            signal,
            AVATAR_STATUS_TIMEOUT_MS,
            (requestSignal) => api.profileAvatar({ signal: requestSignal }),
          );
        } catch (error) {
          if (signal?.aborted) throw error;
          if (isTerminalApiError(error)) return publicUploadFailure(error);
          lastRetryable = publicUploadFailure(
            error,
          ) as AvatarUploadTerminalResult;
          const remaining = deadline - Date.now();
          if (attempt + 1 >= AVATAR_STATUS_MAX_ATTEMPTS || remaining <= 0) {
            return lastRetryable;
          }
          await waitFor(Math.min(delay, remaining), signal);
          delay = Math.min(AVATAR_STATUS_MAX_DELAY_MS, delay * 2);
          continue;
        }

        const avatar = profile.avatar;
        if (
          avatar?.version_id === operationId &&
          avatar.state === "ready" &&
          avatar.delivery_url
        ) {
          const presentation = avatarFromResponse(profile, displayName);
          if (presentation) return { status: "success", avatar: presentation };
        }
        if (
          profile.pending?.version_id === operationId &&
          (profile.pending.state === "failed" ||
            profile.pending.state === "retired")
        ) {
          return {
            status: "terminal_error",
            message:
              "The profile service could not process this image. Your current avatar is unchanged.",
          };
        }
        if (
          avatar?.version_id !== operationId &&
          profile.pending?.version_id !== operationId &&
          attempt >= 2
        ) {
          return {
            status: "retryable_error",
            message:
              "Avatar processing could not be reconciled yet. Your current avatar is unchanged; reopen the editor to check again.",
          };
        }

        const remaining = deadline - Date.now();
        if (attempt + 1 >= AVATAR_STATUS_MAX_ATTEMPTS || remaining <= 0) {
          return lastRetryable;
        }
        await waitFor(Math.min(delay, remaining), signal);
        delay = Math.min(AVATAR_STATUS_MAX_DELAY_MS, delay * 2);
      }
      return lastRetryable;
    },
  };
  port.getStatus = (operationId, signal, displayName) =>
    port.awaitProcessing
      ? port.awaitProcessing(operationId, signal, displayName)
      : Promise.resolve({
          status: "retryable_error",
          message:
            "Avatar processing status is unavailable. Your current avatar is unchanged.",
        });
  return port;
}

/**
 * The explicit inert adapter keeps the UI testable while storage/scanning/
 * processing providers remain gated. It never invents a URL or local source
 * of truth.
 */
export const unavailableAvatarUploadPort: AvatarUploadPort = {
  async upload() {
    return {
      status: "not_available",
      reason: "avatar_upload_not_integrated",
    };
  },
};
