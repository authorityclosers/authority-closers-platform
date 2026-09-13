import { describe, expect, it } from "vitest";

import { googleAuthReturnPath } from "./auth-links";
import { FREE_COURSE_SLUG } from "./course-intent";
import { onboardingHref, onboardingReturnHref } from "./onboarding-route";
import {
  authIntentHref,
  parseSalesAuthNext,
  SALES_XRAY_PATH,
  salesAuthReturnPath,
} from "./sales-auth-return";

const activity = "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be";

describe("bounded Sales authentication continuation", () => {
  it("accepts only the exact Sales path", () => {
    expect(parseSalesAuthNext(SALES_XRAY_PATH)).toBe(SALES_XRAY_PATH);
    for (const value of [
      [SALES_XRAY_PATH],
      [SALES_XRAY_PATH, SALES_XRAY_PATH],
      "/sales-xray/",
      "/sales-xray?tenant=other",
      "https://outside.example/sales-xray",
      " /sales-xray",
      "/sales%2Dxray",
      "sales-xray",
    ]) {
      expect(parseSalesAuthNext(value)).toBeNull();
    }
  });

  it("gives existing course or activity intent precedence over Sales", () => {
    expect(
      authIntentHref("/login", null, FREE_COURSE_SLUG, SALES_XRAY_PATH),
    ).toBe(`/login?course=${FREE_COURSE_SLUG}`);
    expect(
      authIntentHref("/login", activity, FREE_COURSE_SLUG, SALES_XRAY_PATH),
    ).toBe(`/login?course=${FREE_COURSE_SLUG}&activity=${activity}`);
    expect(
      googleAuthReturnPath(
        "authenticate",
        FREE_COURSE_SLUG,
        null,
        SALES_XRAY_PATH,
      ),
    ).toBe(`/home?course=${FREE_COURSE_SLUG}`);
  });

  it("uses the exact signed onboarding return and a bounded learner link", () => {
    expect(salesAuthReturnPath(SALES_XRAY_PATH)).toBe(
      "/onboarding?next=/sales-xray",
    );
    expect(googleAuthReturnPath("register", null, null, SALES_XRAY_PATH)).toBe(
      "/onboarding?next=/sales-xray",
    );
    expect(authIntentHref("/login", null, null, SALES_XRAY_PATH)).toBe(
      "/login?next=%2Fsales-xray",
    );
    expect(onboardingReturnHref("home", null, null, SALES_XRAY_PATH)).toBe(
      SALES_XRAY_PATH,
    );
    expect(onboardingHref("home", null, null, SALES_XRAY_PATH)).toBe(
      "/onboarding?next=%2Fsales-xray",
    );
  });

  it("drops Sales continuation when onboarding is settings-owned", () => {
    expect(
      onboardingReturnHref(
        "settings",
        FREE_COURSE_SLUG,
        activity,
        SALES_XRAY_PATH,
      ),
    ).toBe("/settings");
    expect(
      onboardingHref("settings", FREE_COURSE_SLUG, activity, SALES_XRAY_PATH),
    ).toBe("/onboarding?return=settings");
  });
});
