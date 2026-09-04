import {
  ApiError,
  type LearnerApi,
  type AvatarCropMetadata,
  type ProfileAvatarResponse,
} from "./learner-api";

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
export const AVATAR_HASH_CHUNK_BYTES = 1024 * 1024;

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

/*
 * WebCrypto's one-shot digest API would require allocating the entire image
 * in memory. This small incremental SHA-256 implementation hashes 1 MiB
 * slices instead, keeping the browser's peak allocation bounded without
 * inventing a client-side upload policy. The server remains authoritative for
 * MIME, dimensions, size, scanning, and the declared checksum.
 */
const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
] as const;

function rotateRight(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

class IncrementalSha256 {
  private readonly state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
    0x1f83d9ab, 0x5be0cd19,
  ]);

  private readonly block = new Uint8Array(64);

  private blockLength = 0;

  private bytesHashed = 0;

  update(input: Uint8Array): void {
    let offset = 0;
    this.bytesHashed += input.byteLength;
    while (offset < input.byteLength) {
      const copyLength = Math.min(
        64 - this.blockLength,
        input.byteLength - offset,
      );
      this.block.set(
        input.subarray(offset, offset + copyLength),
        this.blockLength,
      );
      this.blockLength += copyLength;
      offset += copyLength;
      if (this.blockLength === 64) {
        this.compress(this.block);
        this.blockLength = 0;
      }
    }
  }

  digestHex(): string {
    const bitLength = this.bytesHashed * 8;
    const high = Math.floor(bitLength / 0x100000000);
    const low = bitLength >>> 0;
    this.block[this.blockLength] = 0x80;
    this.blockLength += 1;
    if (this.blockLength > 56) {
      this.block.fill(0, this.blockLength);
      this.compress(this.block);
      this.blockLength = 0;
    }
    this.block.fill(0, this.blockLength, 56);
    const view = new DataView(this.block.buffer);
    view.setUint32(56, high >>> 0);
    view.setUint32(60, low);
    this.compress(this.block);
    return Array.from(this.state, (value) =>
      value.toString(16).padStart(8, "0"),
    ).join("");
  }

  private compress(block: Uint8Array): void {
    const words = new Uint32Array(64);
    const view = new DataView(block.buffer, block.byteOffset, block.byteLength);
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(index * 4);
    }
    for (let index = 16; index < 64; index += 1) {
      const value = words[index - 15];
      const sigma0 =
        rotateRight(value, 7) ^ rotateRight(value, 18) ^ (value >>> 3);
      const prior = words[index - 2];
      const sigma1 =
        rotateRight(prior, 17) ^ rotateRight(prior, 19) ^ (prior >>> 10);
      words[index] =
        (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }

    let [a, b, c, d, e, f, g, h] = this.state;
    for (let index = 0; index < 64; index += 1) {
      const sigma1 =
        rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temporary1 =
        (h + sigma1 + choice + SHA256_K[index] + words[index]) >>> 0;
      const sigma0 =
        rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temporary2 = (sigma0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temporary1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temporary1 + temporary2) >>> 0;
    }
    this.state[0] = (this.state[0] + a) >>> 0;
    this.state[1] = (this.state[1] + b) >>> 0;
    this.state[2] = (this.state[2] + c) >>> 0;
    this.state[3] = (this.state[3] + d) >>> 0;
    this.state[4] = (this.state[4] + e) >>> 0;
    this.state[5] = (this.state[5] + f) >>> 0;
    this.state[6] = (this.state[6] + g) >>> 0;
    this.state[7] = (this.state[7] + h) >>> 0;
  }
}

async function checksumSha256(
  file: File,
  signal?: AbortSignal,
): Promise<string | undefined> {
  if (typeof file.slice !== "function") return undefined;
  try {
    const hash = new IncrementalSha256();
    for (
      let offset = 0;
      offset < file.size;
      offset += AVATAR_HASH_CHUNK_BYTES
    ) {
      throwIfAborted(signal);
      const expectedLength = Math.min(
        AVATAR_HASH_CHUNK_BYTES,
        file.size - offset,
      );
      const chunk = await file
        .slice(offset, offset + expectedLength)
        .arrayBuffer();
      throwIfAborted(signal);
      if (chunk.byteLength !== expectedLength) return undefined;
      hash.update(new Uint8Array(chunk));
    }
    return hash.digestHex();
  } catch (error) {
    if (signal?.aborted) throw error;
    return undefined;
  }
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

        let uploadResponse: Response;
        try {
          uploadResponse = await withTimeout(
            signal,
            AVATAR_PUT_TIMEOUT_MS,
            (requestSignal) =>
              fetch(intent.upload_url, {
                method: "PUT",
                headers: intent.upload_headers,
                body: input.file,
                credentials: "omit",
                cache: "no-store",
                redirect: "error",
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
