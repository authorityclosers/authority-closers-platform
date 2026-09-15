import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import CallbackPage from "../auth/callback/page";
import { LoginForm, routeAfterOnboarding } from "../components/login-form";
import { RegistrationForm } from "../components/password-auth-forms";
import { StagingAuthHandoff } from "../components/staging-auth-handoff";
import HomePage from "../home/page";
import LoginPage from "../login/page";
import OnboardingPage from "../onboarding/page";
import RegisterPage from "../register/page";
import SessionExpiredPage from "../session-expired/page";
import { googleAuthReturnPath, googleAuthStartUrl } from "./auth-links";
import {
  courseIntentHref,
  FREE_COURSE_SLUG,
  parseCourseIntent,
} from "./course-intent";
import { onboardingHref, onboardingReturnHref } from "./onboarding-route";

const course = FREE_COURSE_SLUG;
const suffix = `?course=${course}`;

describe("bounded free-course navigation intent", () => {
  it.each([
    undefined,
    null,
    "",
    "other-course",
    "/home",
    "//external.test",
    "https://external.test",
    "authority%2Dclosers-free-course",
    [course],
    [course, course],
    [course, "other"],
    { course },
  ])("drops ambiguous or unsupported input %j", (value) =>
    expect(parseCourseIntent(value)).toBeNull(),
  );
  it("accepts the existing course without granting enrollment or building arbitrary paths", () => {
    expect(parseCourseIntent(course)).toBe(course);
    expect(courseIntentHref("/login", course)).toBe("/login" + suffix);
    expect(courseIntentHref("/home")).toBe("/home");
    expect(
      courseIntentHref("/home", parseCourseIntent("//external.test")),
    ).toBe("/home");
  });
  it.each(["completed", "skipped"] as const)(
    "returns %s password sessions to the same course enrollment surface",
    (status) => {
      expect(routeAfterOnboarding(status, course)).toBe("/home" + suffix);
    },
  );
  it.each(["not_started", "in_progress", undefined] as const)(
    "keeps %s password sessions behind onboarding",
    (status) => {
      expect(routeAfterOnboarding(status, course)).toBe("/onboarding" + suffix);
    },
  );
  it("preserves settings onboarding without allowing course input to replace its destination", () => {
    expect(onboardingHref("settings", course)).toBe(
      "/onboarding?return=settings",
    );
    expect(onboardingReturnHref("settings", course)).toBe("/settings");
    expect(onboardingHref("home", course)).toBe("/onboarding" + suffix);
    expect(onboardingReturnHref("home", course)).toBe("/home" + suffix);
  });
  it.each(["authenticate", "register"] as const)(
    "keeps one signed Google %s return path and the original action",
    (action) => {
      const url = new URL(
        googleAuthStartUrl(action, course),
        "https://app.example.test",
      );
      expect(url.pathname).toBe("/v1/auth/google/start");
      expect(url.searchParams.getAll("return_path")).toEqual([
        googleAuthReturnPath(action, course),
      ]);
      expect(url.searchParams.get("return_path")).toBe(
        (action === "register" ? "/onboarding" : "/home") + suffix,
      );
      expect(url.searchParams.get("action")).toBe(action);
      expect(url.searchParams.has("consent")).toBe(false);
    },
  );
  it("preserves auth cross-links and the real registration GET field without pregranting consent", () => {
    const login = renderToStaticMarkup(<LoginForm courseIntent={course} />);
    const registration = renderToStaticMarkup(
      <RegistrationForm courseIntent={course} />,
    );
    expect(login).toContain('href="/register' + suffix + '"');
    expect(registration).toContain('href="/login' + suffix + '"');
    expect(registration).toContain(
      'name="return_path" value="/onboarding' + suffix + '"',
    );
    expect(registration).toMatch(
      /<input(?=[^>]*name="consent")(?=[^>]*value="true")(?=[^>]*disabled)[^>]*>/,
    );
  });
  it("keeps localhost handoffs on the fixed staging origin", () => {
    const html = renderToStaticMarkup(
      <StagingAuthHandoff
        path="/register"
        action="Account creation"
        courseIntent={course}
      />,
    );
    expect(html).toContain(
      'href="https://staging.authorityclosers.com/register' + suffix + '"',
    );
  });
  it.each([HomePage, LoginPage, OnboardingPage])(
    "keeps the course when a state panel requires sign-in",
    async (page) => {
      const html = renderToStaticMarkup(
        await page({
          searchParams: Promise.resolve({ state: "permission-denied", course }),
        }),
      );
      expect(html).toContain('href="/login' + suffix + '"');
    },
  );
  it("retains course context through onboarding retry and return destinations", async () => {
    const html = renderToStaticMarkup(
      await OnboardingPage({
        searchParams: Promise.resolve({ state: "error-retryable", course }),
      }),
    );
    expect(html).toContain(
      'href="/onboarding' + suffix + '&amp;state=default"',
    );
    expect(html).toContain('href="/home' + suffix + '"');
  });
  it("passes the bounded choice through registration and an expired-session page", async () => {
    const registration = renderToStaticMarkup(
      await RegisterPage({ searchParams: Promise.resolve({ course }) }),
    );
    expect(registration).toContain(
      'name="return_path" value="/onboarding' + suffix + '"',
    );
    const expired = renderToStaticMarkup(
      await SessionExpiredPage({ searchParams: Promise.resolve({ course }) }),
    );
    expect(expired).toContain('href="/register' + suffix + '"');
  });
  it.each([
    "registration_required",
    "consent_required",
    "provider_rejected",
    "provider_unavailable",
  ])(
    "preserves a course during %s recovery without changing consent",
    async (result) => {
      const html = renderToStaticMarkup(
        await CallbackPage({
          searchParams: Promise.resolve({ result, course }),
        }),
      );
      const destination =
        result === "registration_required" || result === "consent_required"
          ? "/register"
          : "/login";
      expect(html).toContain('href="' + destination + suffix + '"');
      expect(html).not.toContain("consent=true");
    },
  );
  it("keeps consent-update recovery on the authenticated renewal flow and rejects inherited result names", async () => {
    const recovery = renderToStaticMarkup(
      await CallbackPage({
        searchParams: Promise.resolve({
          result: "consent_update_required",
          course,
        }),
      }),
    );
    expect(recovery).toContain(
      'href="/consent/renewal?course=authority-closers-free-course"',
    );
    expect(recovery).not.toContain('href="/register');
    for (const result of ["constructor", "__proto__"]) {
      const html = renderToStaticMarkup(
        await CallbackPage({
          searchParams: Promise.resolve({ result, course: [course, course] }),
        }),
      );
      expect(html).toContain("Sign-in result unavailable.");
      expect(html).not.toContain(suffix);
    }
  });
});
