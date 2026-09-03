import { describe, expect, it } from "vitest";

import {
  clampAvatarCrop,
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

  it("rejects empty files and unreadable dimensions before any upload", () => {
    expect(validateAvatarFile({ type: "image/png", size: 0 })).toMatchObject({
      ok: false,
      code: "invalid_size",
    });
    expect(
      validateAvatarFile(file("image/png"), { width: 0, height: 256 }),
    ).toMatchObject({ ok: false, code: "invalid_dimensions" });
    expect(
      validateAvatarFile(file("image/png"), { width: 256, height: 256 }),
    ).toMatchObject({ ok: true });
  });

  it("clamps crop values before handing them to a future adapter", () => {
    expect(clampAvatarCrop({ scale: 4, offsetX: -40, offsetY: 40 })).toEqual({
      scale: 2,
      offsetX: -25,
      offsetY: 25,
    });
  });

  it("keeps the default adapter explicitly unavailable", async () => {
    const result = await unavailableAvatarUploadPort.upload({
      file: file("image/png"),
      crop: { scale: 1, offsetX: 0, offsetY: 0 },
    });

    expect(result).toEqual({
      status: "not_available",
      reason: "avatar_upload_not_integrated",
    });
  });
});
