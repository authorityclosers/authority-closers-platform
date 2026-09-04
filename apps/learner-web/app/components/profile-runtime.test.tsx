import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  new URL("./profile-runtime.tsx", import.meta.url),
  "utf8",
);

describe("ProfileRuntime avatar host wiring", () => {
  it("keeps a host-level success status after the dialog closes", () => {
    expect(source).toContain(
      'setAvatarSuccessMessage("Profile photo updated.")',
    );
    expect(source).toContain("profile-avatar-status--success");
    expect(source).toContain('role="status"');
    expect(source).toContain('aria-live="polite"');
    expect(source).toContain('aria-atomic="true"');
  });

  it("refreshes signed delivery URLs and falls back after image expiry", () => {
    expect(source).toContain("PROFILE_AVATAR_REFRESH_INTERVAL_MS");
    expect(source).toContain("window.setInterval");
    expect(source).toContain("onError={() => {");
    expect(source).toContain("setFailedAvatarUrl(displayAvatar.deliveryUrl)");
    expect(source).toContain("void refreshAvatar()");
  });
});
