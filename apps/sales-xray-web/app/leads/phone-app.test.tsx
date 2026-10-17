import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ANDROID_APP,
  ANDROID_DOWNLOAD_READY,
  PhoneAppBanner,
  PhoneAppDialog,
} from "./phone-app";

describe("getting the phone app", () => {
  it("offers only the real app, never the Dev build", () => {
    const html = renderToStaticMarkup(
      <PhoneAppDialog open onClose={() => undefined} />,
    );
    expect(html).not.toContain("sales-xray-dev-android");
    expect(html).not.toContain("Sales Xray Dev");
    // The signed release build from the apps repo (Orchestrator 2, 18 Oct).
    expect(ANDROID_APP).toBe(
      "https://github.com/authorityclosers/sales-xray-apps/releases/download/sales-xray-android-latest/sales-xray-android.apk",
    );
  });

  it("shows no download until builds are signed with Authority Closers' key", () => {
    const html = renderToStaticMarkup(
      <PhoneAppDialog open onClose={() => undefined} />,
    );
    if (ANDROID_DOWNLOAD_READY) {
      expect(html).toContain(`href="${ANDROID_APP}"`);
      expect(html).toContain("<svg");
    } else {
      expect(html).not.toContain(".apk");
      expect(html).toContain("being tested");
    }
    expect(html).toContain("Coming");
  });

  it("keeps the banner out of the first paint", () => {
    expect(
      renderToStaticMarkup(<PhoneAppBanner onOpen={() => undefined} />),
    ).toBe("");
  });
});
