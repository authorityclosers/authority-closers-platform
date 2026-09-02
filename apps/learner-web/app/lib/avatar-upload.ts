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
  deliveryUrl: string;
  alt: string;
  revision: string;
};

export type AvatarUploadInput = {
  file: File;
  crop: AvatarCrop;
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

export interface AvatarUploadPort {
  upload(input: AvatarUploadInput): Promise<AvatarUploadResult>;
}

export type AvatarFileValidation =
  | { ok: true; mimeType: AvatarAcceptedMimeType }
  | {
      ok: false;
      code: "missing" | "unsupported_type";
      message: string;
    };

export function validateAvatarFile(
  file: Pick<File, "type"> | null | undefined,
): AvatarFileValidation {
  if (!file) {
    return {
      ok: false,
      code: "missing",
      message: "Choose an image to preview your avatar.",
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

  return { ok: true, mimeType: file.type as AvatarAcceptedMimeType };
}

export function clampAvatarCrop(crop: AvatarCrop): AvatarCrop {
  return {
    scale: Math.min(2, Math.max(1, crop.scale)),
    offsetX: Math.min(25, Math.max(-25, crop.offsetX)),
    offsetY: Math.min(25, Math.max(-25, crop.offsetY)),
  };
}

/**
 * The adapter is deliberately inert until the profile object/upload contract
 * is integrated. It gives the UI a typed state boundary without choosing a
 * storage provider, public URL, or client-side source of truth.
 */
export const unavailableAvatarUploadPort: AvatarUploadPort = {
  async upload() {
    return {
      status: "not_available",
      reason: "avatar_upload_not_integrated",
    };
  },
};
