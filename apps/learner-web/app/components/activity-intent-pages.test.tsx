// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "../login/page";
import OnboardingPage from "../onboarding/page";
import SessionExpiredPage from "../session-expired/page";
import { FREE_COURSE_SLUG } from "../lib/course-intent";
import * as bridgeModule from "../lib/dev-api-proxy";
import * as apiModule from "../lib/learner-api";
import type { LearnerApi, OnboardingResponse } from "../lib/learner-api";
import type { QueryValue } from "../lib/surface-state";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const activity = "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be";
const activityHref = "/activity/" + activity;
const course = FREE_COURSE_SLUG;
const intentQuery = "?course=" + course + "&activity=" + activity;
const completedProfile: OnboardingResponse = {
  person_id: "activity-intent-page-fixture",
  experience_context: null,
  learning_goal: null,
  practice_situation: null,
  weekly_minutes: null,
  status: "completed",
  current_step: 3,
  revision: 1,
  updated_at: "2026-09-13T00:00:00Z",
  next_action_href: "/home",
  next_action_reason: "profile_completed",
};

// Await only the page function, then mount its returned client tree. These
// regressions exercise query-to-prop wiring, not Next's RSC transport/router.
describe("activity intent through the actual auth pages", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.stubEnv("NODE_ENV", "test");
    vi.spyOn(bridgeModule, "isStagingAuthenticatedBridge").mockReturnValue(
      false,
    );
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    window.localStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  async function mount(page: Promise<ReactNode>) {
    const content = await page;
    await act(async () => root.render(content));
  }

  function mockCompletedLogin() {
    const loginPassword = vi.fn(async () => undefined);
    const onboarding = vi.fn(async () => completedProfile);
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      loginPassword,
      onboarding,
    } as unknown as LearnerApi);
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});
    return { loginPassword, onboarding, navigate };
  }

  async function submitPassword() {
    const email = container.querySelector<HTMLInputElement>("#login-email");
    const password =
      container.querySelector<HTMLInputElement>("#login-password");
    expect(email).not.toBeNull();
    expect(password).not.toBeNull();
    expect(email!.disabled).toBe(false);
    expect(password!.disabled).toBe(false);
    email!.value = "activity-page-fixture@example.test";
    password!.value = "synthetic-page-password";
    await act(async () =>
      container
        .querySelector("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
  }

  function linkHref(label: string) {
    const link = [...container.querySelectorAll<HTMLAnchorElement>("a")].find(
      (candidate) => candidate.textContent?.trim() === label,
    );
    expect(link, `Expected the visible link: ${label}`).toBeDefined();
    return link!.getAttribute("href");
  }

  describe.each([
    { name: "login", page: LoginPage },
    { name: "session expired", page: SessionExpiredPage },
  ])("$name page", ({ page }) => {
    it.each([
      { name: "canonical UUID", activity, course: undefined },
      {
        name: "uppercase UUID with course",
        activity: activity.toUpperCase(),
        course,
      },
    ])("returns to the fixed activity route from $name", async (query) => {
      const { loginPassword, onboarding, navigate } = mockCompletedLogin();
      await mount(page({ searchParams: Promise.resolve(query) }));
      await submitPassword();

      expect(loginPassword).toHaveBeenCalledExactlyOnceWith(
        "activity-page-fixture@example.test",
        "synthetic-page-password",
      );
      expect(onboarding).toHaveBeenCalledTimes(1);
      expect(loginPassword.mock.invocationCallOrder[0]).toBeLessThan(
        onboarding.mock.invocationCallOrder[0],
      );
      expect(navigate).toHaveBeenCalledExactlyOnceWith(activityHref);
    });

    const rejected: Array<{
      name: string;
      activity: QueryValue;
      course?: QueryValue;
      expected: string;
    }> = [
      { name: "missing activity", activity: undefined, expected: "/home" },
      {
        name: "duplicate activity values",
        activity: [activity, activity],
        course,
        expected: "/home?course=" + course,
      },
      {
        name: "mixed duplicate destinations",
        activity: [activity, "https://outside.example/continue"],
        expected: "/home",
      },
      {
        name: "external URL",
        activity: "https://outside.example/continue",
        expected: "/home",
      },
      {
        name: "activity path instead of UUID",
        activity: activityHref,
        course,
        expected: "/home?course=" + course,
      },
      {
        name: "whitespace-padded UUID and duplicate course",
        activity: " " + activity + " ",
        course: [course, course],
        expected: "/home",
      },
    ];

    it.each(rejected)("falls back safely for $name", async (query) => {
      const { loginPassword, onboarding, navigate } = mockCompletedLogin();
      await mount(page({ searchParams: Promise.resolve(query) }));
      await submitPassword();

      expect(loginPassword).toHaveBeenCalledTimes(1);
      expect(onboarding).toHaveBeenCalledTimes(1);
      expect(navigate).toHaveBeenCalledExactlyOnceWith(query.expected);
    });
  });

  it.each([
    {
      state: "error-retryable",
      label: "Retry this view",
      expected: "/onboarding" + intentQuery + "&state=default",
    },
    {
      state: "permission-denied",
      label: "Go to sign in",
      expected: "/login" + intentQuery,
    },
  ])(
    "preserves validated activity and course in onboarding $state",
    async (testCase) => {
      await mount(
        OnboardingPage({
          searchParams: Promise.resolve({
            state: testCase.state,
            activity: activity.toUpperCase(),
            course,
          }),
        }),
      );

      expect(linkHref(testCase.label)).toBe(testCase.expected);
      expect(linkHref("Back to activity")).toBe(activityHref);
      expect(container.querySelector("form")).toBeNull();
    },
  );

  it.each([
    {
      state: "error-retryable",
      label: "Retry this view",
      expected: "/onboarding?course=" + course + "&state=default",
    },
    {
      state: "permission-denied",
      label: "Go to sign in",
      expected: "/login?course=" + course,
    },
  ])(
    "drops duplicate activity from onboarding $state recovery",
    async (testCase) => {
      await mount(
        OnboardingPage({
          searchParams: Promise.resolve({
            state: testCase.state,
            activity: [activity, activity],
            course,
          }),
        }),
      );

      expect(linkHref(testCase.label)).toBe(testCase.expected);
      expect(linkHref("Back to learner home")).toBe("/home?course=" + course);
      expect(container.querySelector('a[href*="activity="]')).toBeNull();
    },
  );

  it.each([
    {
      state: "error-retryable",
      label: "Retry this view",
      expected: "/onboarding?return=settings&state=default",
    },
    {
      state: "permission-denied",
      label: "Go to sign in",
      expected: "/login",
    },
  ])("lets settings drop both hints in onboarding $state", async (testCase) => {
    await mount(
      OnboardingPage({
        searchParams: Promise.resolve({
          state: testCase.state,
          return: "settings",
          activity,
          course,
        }),
      }),
    );

    expect(linkHref(testCase.label)).toBe(testCase.expected);
    expect(linkHref("Back to settings")).toBe("/settings");
    expect(container.querySelector('a[href*="activity="]')).toBeNull();
    expect(container.querySelector('a[href*="course="]')).toBeNull();
    expect(container.querySelector('a[href^="/activity/"]')).toBeNull();
  });
});
