import { ApiError, type LearnerApi, type ProfileAvatarResponse } from "./learner-api";

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
  upload(input: AvatarUploadInput): Promise<AvatarUploadResult>;
  /**
   * The adapter owns provider-specific polling/subscription details. The UI
   * only consumes the final server-confirmed result when one is available.
   */
  awaitProcessing?: (
    operationId: string,
    signal?: AbortSignal,
  ) => Promise<AvatarUploadTerminalResult>;
  /** Compatibility status probe for the existing crop dialog contract. */
  getStatus?: (
    operationId: string,
    signal?: AbortSignal,
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

export function clampAvatarCrop(crop: AvatarCrop): AvatarCrop {
  return {
    scale: Math.min(2, Math.max(1, finiteOr(crop.scale, 1))),
    offsetX: Math.min(25, Math.max(-25, finiteOr(crop.offsetX, 0))),
    offsetY: Math.min(25, Math.max(-25, finiteOr(crop.offsetY, 0))),
  };
}

/**
 * Convert the keyboard-friendly preview controls to the normalized crop
 * contract accepted by the server. The UI never sends CSS transforms as
 * canonical media data.
 */
export function toAvatarCropMetadata(crop: AvatarCrop): {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: number;
} {
  const bounded = clampAvatarCrop(crop);
  const side = 1 / bounded.scale;
  const travel = 1 - side;
  const x = 0.5 - side / 2 - (bounded.offsetX / 25) * (travel / 2);
  const y = 0.5 - side / 2 - (bounded.offsetY / 25) * (travel / 2);
  return {
    x: Math.min(1 - side, Math.max(0, x)),
    y: Math.min(1 - side, Math.max(0, y)),
    width: side,
    height: side,
    rotation_degrees: 0,
  };
}

function initialsFor(displayName: string): string {
  return (
    displayName
      .split(" ")
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase() || "AC"
  );
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
  return {
    assetId: avatar.asset_id,
    versionId: avatar.version_id,
    deliveryUrl: avatar.delivery_url,
    alt: `${displayName || initialsFor(displayName)}'s profile photo`,
    revision: String(avatar.version_number),
  };
}

function publicUploadFailure(error: unknown): AvatarUploadResult {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) {
      return {
        status: "terminal_error",
        message:
          "Your profile session is no longer authorized. Sign in again before changing your avatar.",
      };
    }
    if ([400, 409, 413, 422].includes(error.status)) {
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

function publicDirectUploadFailure(error: unknown): AvatarUploadResult {
  if (error instanceof DirectUploadError && [400, 401, 403, 413, 422].includes(error.status)) {
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

async function checksumSha256(file: File): Promise<string | undefined> {
  if (!globalThis.crypto?.subtle) return undefined;
  try {
    const digest = await globalThis.crypto.subtle.digest(
      "SHA-256",
      await file.arrayBuffer(),
    );
    return Array.from(new Uint8Array(digest), (value) =>
      value.toString(16).padStart(2, "0"),
    ).join("");
  } catch {
    return undefined;
  }
}

type AvatarUploadApi = Pick<
  LearnerApi,
  | "createProfileAvatarUpload"
  | "completeProfileAvatarUpload"
  | "profileAvatar"
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
    return Promise.reject(new DOMException("The operation was aborted.", "AbortError"));
  }
  return new Promise((resolve, reject) => {
    const timeout = globalThis.setTimeout(finish, ms);
    function abort() {
      globalThis.clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("The operation was aborted.", "AbortError"));
    }
    function finish() {
      signal?.removeEventListener("abort", abort);
      resolve();
    }
    signal?.addEventListener("abort", abort, { once: true });
  });
}

export function createApiAvatarUploadPort(
  api: AvatarUploadApi,
): AvatarUploadPort {
  const port: AvatarUploadPort = {
    async upload(input) {
      const validation = validateAvatarFile(input.file);
      if (!validation.ok) {
        return { status: "terminal_error", message: validation.message };
      }
      const crop = toAvatarCropMetadata(input.crop);
      try {
        const checksum = await checksumSha256(input.file);
        const intent = await api.createProfileAvatarUpload({
          filename: input.file.name || "avatar",
          content_type: validation.mimeType,
          content_length: input.file.size,
          asset_id: input.currentAvatar?.assetId ?? null,
          supersedes_version_id: input.currentAvatar?.versionId ?? null,
          crop,
        });
        if (new Date(intent.expires_at).getTime() <= Date.now()) {
          return {
            status: "retryable_error",
            message:
              "The avatar upload window expired before it started. Your current avatar is unchanged; try again.",
          };
        }

        let uploadResponse: Response;
        try {
          uploadResponse = await fetch(intent.upload_url, {
            method: "PUT",
            headers: intent.upload_headers,
            body: input.file,
            credentials: "omit",
            cache: "no-store",
            redirect: "error",
          });
        } catch (error) {
          return publicDirectUploadFailure(error);
        }
        if (!uploadResponse.ok) {
          return publicDirectUploadFailure(new DirectUploadError(uploadResponse.status));
        }

        const completed = await api.completeProfileAvatarUpload(
          intent.upload_id,
          {
            actual_bytes: input.file.size,
            ...(checksum ? { checksum_sha256: checksum } : {}),
          },
        );
        if (completed.state === "failed") {
          return {
            status: "terminal_error",
            message:
              "The profile service rejected this image. Your current avatar is unchanged.",
          };
        }
        const profile = await api.profileAvatar();
        const avatar = avatarFromResponse(profile, input.displayName || "Learner");
        if (avatar && avatar.versionId === intent.media_version_id) {
          return { status: "success", avatar };
        }
        return asProcessing(intent.media_version_id, profile);
      } catch (error) {
        return publicUploadFailure(error);
      }
    },

    async awaitProcessing(operationId, signal) {
      for (let attempt = 0; attempt < 12; attempt += 1) {
        const profile = await api.profileAvatar({ signal });
        const avatar = profile.avatar;
        if (
          avatar?.version_id === operationId &&
          avatar.state === "ready" &&
          avatar.delivery_url
        ) {
          const presentation = avatarFromResponse(profile, "Learner");
          if (presentation) return { status: "success", avatar: presentation };
        }
        if (
          profile.pending?.version_id === operationId &&
          profile.pending.state === "failed"
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
        await waitFor(750, signal);
      }
      return {
        status: "retryable_error",
        message:
          "Avatar processing is taking longer than expected. Your current avatar is unchanged; reopen the editor to check again.",
      };
    },
  };
  port.getStatus = (operationId, signal) =>
    port.awaitProcessing
      ? port.awaitProcessing(operationId, signal)
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
