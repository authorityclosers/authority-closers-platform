import { describe, expect, it, vi } from "vitest";

import {
  AVATAR_HASH_CHUNK_BYTES,
  clampAvatarCrop,
  coverCropExtent,
  createApiAvatarUploadPort,
  toAvatarCropMetadata,
  unavailableAvatarUploadPort,
  validateAvatarFile,
} from "./avatar-upload";
import { ApiError } from "./learner-api";

function file(
  type: string,
  bytes = [1, 2, 3, 4],
  onSlice?: (start: number, end: number) => void,
): File {
  const data = Uint8Array.from(bytes);
  return {
    name: "avatar",
    type,
    size: data.byteLength,
    slice(start: number, end?: number) {
      onSlice?.(start, end ?? data.byteLength);
      const chunk = data.slice(start, end);
      return {
        arrayBuffer: async () =>
          chunk.buffer.slice(
            chunk.byteOffset,
            chunk.byteOffset + chunk.byteLength,
          ),
      } as Blob;
    },
  } as unknown as File;
}

describe("avatar upload boundary", () => {
  const bytesChecksum =
    "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a";

  it("accepts the browser-preview formats without guessing service limits", () => {
    expect(validateAvatarFile(file("image/jpeg"))).toMatchObject({ ok: true });
    expect(validateAvatarFile(file("image/png"))).toMatchObject({ ok: true });
    expect(validateAvatarFile(file("image/webp"))).toMatchObject({ ok: true });
    expect(validateAvatarFile(file("image/svg+xml"))).toMatchObject({
      ok: false,
      code: "unsupported_type",
    });
  });

  it("hashes bounded file slices before requesting an upload intent", async () => {
    const bytes = Array.from(
      { length: AVATAR_HASH_CHUNK_BYTES + 17 },
      (_, index) => index % 256,
    );
    const slices: number[] = [];
    const image = file("image/png", bytes, (start, end) => {
      slices.push(end - start);
    });
    const createProfileAvatarUpload = vi.fn(async () => ({
      upload_id: "upload-expired",
      media_id: "asset-1",
      media_version_id: "version-1",
      version_number: 1,
      state: "uploading" as const,
      object_key: "private/avatar",
      upload_url: "https://upload.invalid/avatar",
      upload_headers: {},
      expires_at: new Date(Date.now() - 1_000).toISOString(),
      max_bytes: 5_000_000,
    }));
    const port = createApiAvatarUploadPort({
      createProfileAvatarUpload,
      completeProfileAvatarUpload: vi.fn(),
      profileAvatar: vi.fn(),
    });

    await expect(
      port.upload({
        file: image,
        crop: { scale: 1, offsetX: 0, offsetY: 0 },
        sourceDimensions: { width: 1600, height: 900 },
      }),
    ).resolves.toMatchObject({ status: "retryable_error" });
    expect(slices).toEqual([AVATAR_HASH_CHUNK_BYTES, 17]);
    expect(createProfileAvatarUpload).toHaveBeenCalledWith(
      expect.objectContaining({
        checksum_sha256:
          "198fe22858bf90dd34cba065bf3e3d4680918f930e94ce51807b9b3055f2eb1e",
      }),
      expect.anything(),
    );
  });

  it("fails closed when the browser cannot provide complete file chunks", async () => {
    const createProfileAvatarUpload = vi.fn();
    const port = createApiAvatarUploadPort({
      createProfileAvatarUpload,
      completeProfileAvatarUpload: vi.fn(),
      profileAvatar: vi.fn(),
    });
    const unreadable = {
      name: "avatar.png",
      type: "image/png",
      size: 4,
      slice: () =>
        ({ arrayBuffer: async () => new ArrayBuffer(0) }) as unknown as Blob,
    } as unknown as File;

    await expect(
      port.upload({
        file: unreadable,
        crop: { scale: 1, offsetX: 0, offsetY: 0 },
        sourceDimensions: { width: 1000, height: 1000 },
      }),
    ).resolves.toMatchObject({ status: "terminal_error" });
    expect(createProfileAvatarUpload).not.toHaveBeenCalled();
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
      x: 0.125,
      y: 0.375,
      width: 0.5,
      height: 0.5,
      rotation_degrees: 0,
    });
  });

  it("matches object-fit cover source extents for landscape, portrait, scale, and edge crops", () => {
    expect(coverCropExtent({ width: 1600, height: 900 })).toEqual({
      width: 0.5625,
      height: 1,
    });
    expect(
      toAvatarCropMetadata(
        { scale: 1, offsetX: 0, offsetY: 0 },
        { width: 1600, height: 900 },
      ),
    ).toMatchObject({ x: 0.21875, y: 0, width: 0.5625, height: 1 });
    expect(
      toAvatarCropMetadata(
        { scale: 2, offsetX: 25, offsetY: -25 },
        { width: 1600, height: 900 },
      ),
    ).toMatchObject({
      x: 0.2890625,
      y: 0.375,
      width: 0.28125,
      height: 0.5,
    });
    expect(
      toAvatarCropMetadata(
        { scale: 2, offsetX: 25, offsetY: -25 },
        { width: 900, height: 1600 },
      ),
    ).toMatchObject({
      x: 0.125,
      y: 0.4296875,
      width: 0.5,
      height: 0.28125,
    });
    const multiScale = toAvatarCropMetadata(
      { scale: 1.5, offsetX: 25, offsetY: -25 },
      { width: 1600, height: 900 },
    );
    expect(multiScale).toMatchObject({
      x: 0.21875,
      width: 0.375,
      height: 2 / 3,
    });
    expect(multiScale.y).toBeCloseTo(1 / 3, 12);
    expect(
      toAvatarCropMetadata(
        { scale: 1, offsetX: 100, offsetY: -100 },
        { width: 900, height: 1600 },
      ),
    ).toMatchObject({ x: 0, y: 0.359375, width: 1, height: 0.5625 });
  });

  it("keeps the default adapter explicitly unavailable", async () => {
    const result = await unavailableAvatarUploadPort.upload({
      file: file("image/png"),
      crop: { scale: 1, offsetX: 0, offsetY: 0 },
      sourceDimensions: { width: 1000, height: 1000 },
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
      upload_headers: {
        "Content-Type": "image/png",
        "x-content-sha256": bytesChecksum,
      },
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
            x: 0.125,
            y: 0.375,
            width: 0.5,
            height: 0.5,
            rotation_degrees: 0,
          },
          checksum_sha256: bytesChecksum,
        });
        return intent;
      }),
      completeProfileAvatarUpload: vi.fn(async (_uploadId, input) => {
        expect(input).toEqual({
          actual_bytes: 4,
          checksum_sha256: bytesChecksum,
        });
        return {} as never;
      }),
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
          size: 4,
          slice: file("image/png").slice,
        } as unknown as File,
        crop: { scale: 2, offsetX: 25, offsetY: -25 },
        sourceDimensions: { width: 1000, height: 1000 },
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
          headers: intent.upload_headers,
        }),
      );
      expect(
        new Headers(fetchSpy.mock.calls[0]?.[1]?.headers).get(
          "x-content-sha256",
        ),
      ).toBe(bytesChecksum);
      expect(api.completeProfileAvatarUpload).toHaveBeenCalledWith(
        intent.upload_id,
        { actual_bytes: 4, checksum_sha256: bytesChecksum },
        expect.anything(),
      );
      expect(result).toEqual({
        status: "success",
        avatar: expect.objectContaining({
          assetId: "asset-1",
          versionId: "version-2",
          deliveryUrl: profile.avatar.delivery_url,
          alt: "Learner's profile photo",
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
        sourceDimensions: { width: 1000, height: 1000 },
        displayName: "Learner",
      });
      expect(result).toMatchObject({ status: "terminal_error" });
      expect(api.completeProfileAvatarUpload).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("propagates cancellation through the private PUT instead of reporting success", async () => {
    const intent = {
      upload_id: "upload-3",
      media_id: "asset-1",
      media_version_id: "version-3",
      version_number: 3,
      state: "uploading" as const,
      object_key: "private/avatar",
      upload_url: "https://upload.invalid/avatar",
      upload_headers: {
        "Content-Type": "image/png",
        "x-content-sha256":
          "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a",
      },
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      max_bytes: 5_000_000,
    };
    const api = {
      createProfileAvatarUpload: vi.fn(async () => intent),
      completeProfileAvatarUpload: vi.fn(),
      profileAvatar: vi.fn(),
    } as Parameters<typeof createApiAvatarUploadPort>[0];
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (_input, init) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(
              new DOMException("The operation was aborted.", "AbortError"),
            );
          });
        });
      });
    const controller = new AbortController();
    const pending = createApiAvatarUploadPort(api).upload(
      {
        file: file("image/png"),
        crop: { scale: 1, offsetX: 0, offsetY: 0 },
        sourceDimensions: { width: 1000, height: 1000 },
      },
      controller.signal,
    );

    try {
      await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled(), {
        timeout: 1_000,
      });
      controller.abort();
      await expect(pending).rejects.toMatchObject({ name: "AbortError" });
      expect(api.completeProfileAvatarUpload).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("carries the real display name through processing confirmation", async () => {
    const profile = {
      avatar: {
        asset_id: "asset-2",
        version_id: "version-2",
        version_number: 2,
        state: "ready" as const,
        delivery_url: "https://delivery.invalid/avatar-2",
        content_type: "image/png",
        size_px: 256,
        avatar_crop: null,
        supersedes_version_id: "version-1",
        updated_at: "2026-09-03T00:00:00Z",
      },
      pending: null,
    };
    const port = createApiAvatarUploadPort({
      createProfileAvatarUpload: vi.fn(),
      completeProfileAvatarUpload: vi.fn(),
      profileAvatar: vi.fn(async () => profile),
    });

    await expect(
      port.awaitProcessing?.("version-2", undefined, "Priya Shah"),
    ).resolves.toEqual({
      status: "success",
      avatar: expect.objectContaining({
        alt: "Priya Shah's profile photo",
      }),
    });
  });

  it("retries transient status reads with bounded backoff and stops on terminal responses", async () => {
    vi.useFakeTimers();
    try {
      const profile = {
        avatar: {
          asset_id: "asset-2",
          version_id: "version-2",
          version_number: 2,
          state: "ready" as const,
          delivery_url: "https://delivery.invalid/avatar-2",
          content_type: "image/png",
          size_px: 256,
          avatar_crop: null,
          supersedes_version_id: "version-1",
          updated_at: "2026-09-03T00:00:00Z",
        },
        pending: null,
      };
      const profileAvatar = vi
        .fn()
        .mockRejectedValueOnce(new TypeError("temporary network failure"))
        .mockResolvedValueOnce(profile);
      const port = createApiAvatarUploadPort({
        createProfileAvatarUpload: vi.fn(),
        completeProfileAvatarUpload: vi.fn(),
        profileAvatar,
      });
      const resultPromise = port.awaitProcessing?.(
        "version-2",
        undefined,
        "Priya Shah",
      );
      await vi.advanceTimersByTimeAsync(750);
      await expect(resultPromise).resolves.toMatchObject({
        status: "success",
        avatar: { alt: "Priya Shah's profile photo" },
      });
      expect(profileAvatar).toHaveBeenCalledTimes(2);

      const terminalPort = createApiAvatarUploadPort({
        createProfileAvatarUpload: vi.fn(),
        completeProfileAvatarUpload: vi.fn(),
        profileAvatar: vi.fn(async () => {
          throw new ApiError(403, "profile denied");
        }),
      });
      await expect(
        terminalPort.awaitProcessing?.("version-2", undefined, "Priya Shah"),
      ).resolves.toMatchObject({ status: "terminal_error" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("aborts a pending status read without waiting for the timeout", async () => {
    const controller = new AbortController();
    const profileAvatar = vi.fn(() => new Promise<never>(() => undefined));
    const port = createApiAvatarUploadPort({
      createProfileAvatarUpload: vi.fn(),
      completeProfileAvatarUpload: vi.fn(),
      profileAvatar,
    });
    const pending = port.awaitProcessing?.("version-2", controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
