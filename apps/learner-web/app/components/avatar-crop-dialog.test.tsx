import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { applyAvatarGesture, AvatarCropDialog } from "./avatar-crop-dialog";

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
    expect(html).toContain("Fine-tune with keyboard");
    expect(html).toContain("Drop a photo here");
    expect(html).toContain("scroll or pinch to zoom");
    expect(html).toContain("Your current avatar stays in place");
    expect(html).toContain("Current avatar");
    expect(html).toContain("fail-closed");
  });

  it("clamps direct pan and zoom gestures to the upload contract", () => {
    expect(
      applyAvatarGesture({ scale: 1.5, offsetX: 10, offsetY: -10 }, 50, -50, 2),
    ).toEqual({ scale: 2, offsetX: 25, offsetY: -25 });
  });
});
