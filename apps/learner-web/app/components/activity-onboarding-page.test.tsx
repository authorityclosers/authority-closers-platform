// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OnboardingPage from "../onboarding/page";
import { FREE_COURSE_SLUG } from "../lib/course-intent";
import type { OnboardingResponse } from "../lib/learner-api";
import type { QueryValue } from "../lib/surface-state";

const { pageApi } = vi.hoisted(() => ({
  pageApi: {
    onboarding: vi.fn(),
    saveOnboarding: vi.fn(),
  },
}));

vi.mock("../lib/learner-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/learner-api")>();
  return { ...actual, createLearnerApi: () => pageApi };
});

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const activity = "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be";
const course = FREE_COURSE_SLUG;
const baseProfile: OnboardingResponse = {
  person_id: "onboarding-page-completion-fixture",
  experience_context: null,
  learning_goal: null,
  practice_situation: null,
  weekly_minutes: null,
  status: "not_started",
  current_step: 1,
  revision: 7,
  updated_at: "2026-09-13T00:00:00Z",
  next_action_href: "/onboarding",
  next_action_reason: "profile_not_started",
};
const destinations: Array<{
  name: string;
  query: { activity?: QueryValue; course?: QueryValue; return?: QueryValue };
  href: string;
  label: string;
}> = [
  {
    name: "activity",
    query: { activity: activity.toUpperCase(), course },
    href: "/activity/" + activity,
    label: "Resume activity",
  },
  {
    name: "settings precedence",
    query: { activity, course, return: "settings" },
    href: "/settings",
    label: "Return to settings",
  },
  {
    name: "duplicate activity fallback",
    query: { activity: [activity, activity], course },
    href: "/home?course=" + course,
    label: "Open learner home",
  },
  {
    name: "default home",
    query: {},
    href: "/home",
    label: "Open learner home",
  },
];

// Mount the actual default page, including its unmodified form. Hoisting the
// API fixture covers the form's module-level default client, so this exercises
// the page-to-form handoff rather than passing return props into the form here.
describe("default onboarding page completion preserves navigation", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    pageApi.onboarding.mockReset();
    pageApi.saveOnboarding.mockReset();
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    window.localStorage.clear();
  });

  it.each(
    (["skipped", "completed"] as const).flatMap((status) =>
      destinations.map((destination) => ({ status, ...destination })),
    ),
  )(
    "returns to $name after $status on the default page",
    async ({ status, query, href, label }) => {
      const profile: OnboardingResponse =
        status === "completed"
          ? {
              ...baseProfile,
              status: "in_progress",
              current_step: 3,
              experience_context: "sales",
              learning_goal: "Run clearer discovery calls",
              practice_situation: "A discovery call to prepare for",
              weekly_minutes: 30,
            }
          : baseProfile;
      pageApi.onboarding.mockResolvedValue(profile);
      pageApi.saveOnboarding.mockResolvedValue({
        ...profile,
        status,
        revision: profile.revision + 1,
        next_action_href: "/home",
      });
      const page = await OnboardingPage({
        searchParams: Promise.resolve(query),
      });
      await act(async () => root.render(page));
      expect(pageApi.onboarding).toHaveBeenCalledTimes(1);
      expect(pageApi.saveOnboarding).not.toHaveBeenCalled();
      const action = [...container.querySelectorAll("button")].find(
        (button) =>
          button.textContent?.trim() ===
          (status === "skipped" ? "Skip setup" : "Save profile"),
      );
      expect(action).toBeDefined();
      expect(action!.disabled).toBe(false);
      await act(async () => action!.click());
      expect(pageApi.saveOnboarding).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({ status, currentStep: profile.current_step }),
        profile.revision,
      );
      const continuation = container.querySelector(".onboarding-complete a");
      expect(continuation?.getAttribute("href")).toBe(href);
      expect(continuation?.textContent?.trim()).toBe(label);
    },
  );
});
