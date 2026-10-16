import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ANDROID_APP,
  ANDROID_DEV_APP,
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

  it("first paints the download with a QR code, the same on the server and the phone", () => {
    const html = renderToStaticMarkup(
      <PhoneAppDialog open onClose={() => undefined} />,
    );
    expect(html).toContain("Download for Android");
    expect(html).toContain(`href="${ANDROID_APP}"`);
    expect(html).toContain("<svg");
    expect(html).toContain("Coming");
  });

  it("keeps the banner out of the first paint", () => {
    expect(
      renderToStaticMarkup(<PhoneAppBanner onOpen={() => undefined} />),
    ).toBe("");
  });
});
