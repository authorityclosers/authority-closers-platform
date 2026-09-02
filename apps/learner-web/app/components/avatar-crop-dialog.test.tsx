import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AvatarCropDialog } from "./avatar-crop-dialog";

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
    expect(html).toContain('accept="image/jpeg,image/png,image/webp"');
    expect(html).toContain("Use the sliders with a keyboard");
    expect(html).toContain("Your current avatar stays in place");
    expect(html).toContain("Current avatar");
    expect(html).toContain("preview-only");
  });
});
