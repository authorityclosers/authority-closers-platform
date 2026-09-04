import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  applyAvatarGesture,
  applyAvatarKeyboard,
  AvatarCropDialog,
  canCommitAvatarResult,
  DEFAULT_AVATAR_CROP,
} from "./avatar-crop-dialog";

describe("AvatarCropDialog", () => {
  it("exposes an accessible local preview and crop alternative", () => {
    const html = renderToStaticMarkup(
      createElement(AvatarCropDialog, {
        displayName: "Alex Morgan",
        onClose: vi.fn(),
      }),
    );

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-describedby="avatar-file-hint"');
    expect(html).toContain('accept="image/jpeg,image/png,image/webp"');
    expect(html).toContain("Drop a photo here");
    expect(html).toContain("scroll or pinch to zoom");
    expect(html).toContain("Keyboard: focus the preview");
    expect(html).toContain("Reset framing");
    expect(html).not.toContain('type="range"');
    expect(html).toContain("Your current avatar stays in place");
    expect(html).toContain("Current avatar");
    expect(html).toContain("fail-closed");
    expect(html).toContain(">AM<");

    const squareHtml = renderToStaticMarkup(
      createElement(AvatarCropDialog, {
        cropShape: "square",
        displayName: "Alex Morgan",
        onClose: vi.fn(),
      }),
    );
    expect(squareHtml).toContain('aria-label="Square avatar crop preview"');
  });

  it("clamps direct pan and zoom gestures to the upload contract", () => {
    expect(
      applyAvatarGesture({ scale: 1.5, offsetX: 10, offsetY: -10 }, 50, -50, 2),
    ).toEqual({ scale: 2, offsetX: 25, offsetY: -25 });
  });

  it("keeps keyboard framing bounded without slider controls", () => {
    expect(applyAvatarKeyboard(DEFAULT_AVATAR_CROP, "ArrowLeft")).toEqual({
      scale: 1,
      offsetX: -2,
      offsetY: 0,
    });
    expect(
      applyAvatarKeyboard(
        { scale: 2, offsetX: 25, offsetY: -25 },
        "ArrowDown",
        true,
      ),
    ).toEqual({ scale: 2, offsetX: 25, offsetY: -20 });
    expect(
      applyAvatarKeyboard({ scale: 1.5, offsetX: 10, offsetY: -8 }, "-"),
    ).toEqual({
      scale: 1.41,
      offsetX: 10,
      offsetY: -8,
    });
    expect(
      applyAvatarKeyboard({ scale: 1.5, offsetX: 10, offsetY: -8 }, "Home"),
    ).toEqual(DEFAULT_AVATAR_CROP);
    expect(applyAvatarKeyboard(DEFAULT_AVATAR_CROP, "Tab")).toBeNull();
  });

  it("rejects adapter results after cancellation or unmount", () => {
    const controller = new AbortController();
    expect(canCommitAvatarResult(controller.signal, true)).toBe(true);

    controller.abort();
    expect(canCommitAvatarResult(controller.signal, true)).toBe(false);
    expect(canCommitAvatarResult(new AbortController().signal, false)).toBe(
      false,
    );
  });

  it("keeps cancellation, offline state, and direct input paths fail-closed", () => {
    const source = readFileSync(
      new URL("./avatar-crop-dialog.tsx", import.meta.url),
      "utf8",
    );
    expect(source).toContain("useSyncExternalStore");
    expect(source).toContain("activeAbortRef.current?.abort();");
    expect(source).toContain("You’re offline. Reconnect before uploading");
    expect(source).toContain("onPointerDown={beginPointerGesture}");
    expect(source).toContain("onWheel={(event)");
    expect(source).not.toContain('type="range"');
  });
});
