import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ANDROID_APP,
  ANDROID_DEV_APP,
  ANDROID_DOWNLOAD_READY,
  appLink,
  PhoneAppBanner,
  PhoneAppDialog,
} from "./phone-app";

describe("getting the phone app", () => {
  it("links each site to its own app", () => {
    expect(appLink(false)).toBe(ANDROID_APP);
    expect(appLink(true)).toBe(ANDROID_DEV_APP);
    expect(ANDROID_APP).toMatch(
      /^https:\/\/github\.com\/.+\/releases\/download\/sales-xray-android-latest\/sales-xray-android\.apk$/,
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
