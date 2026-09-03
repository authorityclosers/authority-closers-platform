import { describe, expect, it, vi } from "vitest";

import {
  clampAvatarCrop,
  createApiAvatarUploadPort,
  toAvatarCropMetadata,
  unavailableAvatarUploadPort,
  validateAvatarFile,
} from "./avatar-upload";

function file(type: string): File {
  return { name: "avatar", type, size: 1024 } as File;
}

describe("avatar upload boundary", () => {
  it("accepts the browser-preview formats without guessing service limits", () => {
    expect(validateAvatarFile(file("image/jpeg"))).toMatchObject({ ok: true });
    expect(validateAvatarFile(file("image/png"))).toMatchObject({ ok: true });
    expect(validateAvatarFile(file("image/webp"))).toMatchObject({ ok: true });
    expect(validateAvatarFile(file("image/svg+xml"))).toMatchObject({
      ok: false,
      code: "unsupported_type",
    });
  });

  it("clamps crop values before handing them to a future adapter", () => {
    expect(clampAvatarCrop({ scale: 4, offsetX: -40, offsetY: 40 })).toEqual({
      scale: 2,
      offsetX: -25,
      offsetY: 25,
    });
  });

  it("serializes the local crop controls to bounded server metadata", () => {
    expect(
      toAvatarCropMetadata({ scale: 2, offsetX: 25, offsetY: -25 }),
    ).toEqual({
      x: 0,
      y: 0.5,
      width: 0.5,
      height: 0.5,
      rotation_degrees: 0,
    });
  });

  it("keeps the default adapter explicitly unavailable", async () => {
    const result = await unavailableAvatarUploadPort.upload({
      file: file("image/png"),
      crop: { scale: 1, offsetX: 0, offsetY: 0 },
      displayName: "Learner",
    });

    expect(result).toEqual({
      status: "not_available",
      reason: "avatar_upload_not_integrated",
    });
  });

  it("sends a tenant-scoped superseding upload and only returns a confirmed URL", async () => {
    const intent = {
      upload_id: "upload-2",
      media_id: "asset-1",
      media_version_id: "version-2",
      version_number: 2,
      state: "uploading" as const,
      object_key: "private/should-never-be-rendered",
      upload_url: "https://upload.invalid/avatar",
      upload_headers: { "Content-Type": "image/png" },
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      max_bytes: 5_000_000,
    };
    const profile = {
      avatar: {
        asset_id: "asset-1",
        version_id: "version-2",
        version_number: 2,
        state: "ready" as const,
        delivery_url: "https://delivery.invalid/avatar?sig=short-lived",
        content_type: "image/png",
        size_px: 256,
        avatar_crop: null,
        supersedes_version_id: "version-1",
        updated_at: "2026-09-03T00:00:00Z",
      },
      pending: null,
    };
    const api = {
      createProfileAvatarUpload: vi.fn(async (input) => {
        expect(input).toMatchObject({
          asset_id: "asset-1",
          supersedes_version_id: "version-1",
          crop: {
            x: 0,
            y: 0.5,
            width: 0.5,
            height: 0.5,
            rotation_degrees: 0,
          },
        });
        return intent;
      }),
      completeProfileAvatarUpload: vi.fn(async () => ({}) as never),
      profileAvatar: vi.fn(async () => profile),
    } as Parameters<typeof createApiAvatarUploadPort>[0];
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 200 }));

    try {
      const result = await createApiAvatarUploadPort(api).upload({
        file: {
          name: "headshot.png",
          type: "image/png",
          size: 2048,
          arrayBuffer: async () => new ArrayBuffer(0),
        } as File,
        crop: { scale: 2, offsetX: 25, offsetY: -25 },
        displayName: "Learner",
        currentAvatar: {
          assetId: "asset-1",
          versionId: "version-1",
          deliveryUrl: "https://delivery.invalid/old",
          alt: "Learner's profile photo",
          revision: "1",
        },
      });

      expect(fetchSpy).toHaveBeenCalledWith(
        intent.upload_url,
        expect.objectContaining({
          method: "PUT",
          credentials: "omit",
          redirect: "error",
        }),
      );
      expect(result).toEqual({
        status: "success",
        avatar: expect.objectContaining({
          assetId: "asset-1",
          versionId: "version-2",
          deliveryUrl: profile.avatar.delivery_url,
        }),
      });
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("maps a rejected private upload to a safe terminal result", async () => {
    const api = {
      createProfileAvatarUpload: vi.fn(async () => ({
        upload_id: "upload-2",
        media_id: "asset-1",
        media_version_id: "version-2",
        version_number: 2,
        state: "uploading" as const,
        object_key: "private/not-rendered",
        upload_url: "https://upload.invalid/avatar",
        upload_headers: {},
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        max_bytes: 5_000_000,
      })),
      completeProfileAvatarUpload: vi.fn(),
      profileAvatar: vi.fn(),
    } as Parameters<typeof createApiAvatarUploadPort>[0];
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 403 }));

    try {
      const result = await createApiAvatarUploadPort(api).upload({
        file: file("image/png"),
        crop: { scale: 1, offsetX: 0, offsetY: 0 },
        displayName: "Learner",
      });
      expect(result).toMatchObject({ status: "terminal_error" });
      expect(api.completeProfileAvatarUpload).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });
});
