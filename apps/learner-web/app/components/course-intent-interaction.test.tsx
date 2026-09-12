// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type LearnerApi,
  type OnboardingResponse,
  type ProgramDetailResponse,
} from "../lib/learner-api";
import { FREE_COURSE_SLUG } from "../lib/course-intent";
import { OnboardingForm } from "./onboarding-form";
import { LoginForm } from "./login-form";
import * as apiModule from "../lib/learner-api";
import { PublicProgramDetail } from "./learner-runtime";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const course = FREE_COURSE_SLUG;
const activity = "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be";
const activityHref = "/activity/" + activity;
const recoveryCases = [
  {
    name: "course only",
    activityIntent: null,
    returnHref: undefined,
    href: "/session-expired?course=" + course,
  },
  {
    name: "course and activity",
    activityIntent: activity,
    returnHref: undefined,
    href: "/session-expired?course=" + course + "&activity=" + activity,
  },
  {
    name: "settings precedence",
    activityIntent: activity,
    returnHref: "/settings",
    href: "/session-expired",
  },
] as const;
const profile: OnboardingResponse = {
  person_id: "course-intent-fixture",
  experience_context: null,
  learning_goal: null,
  practice_situation: null,
  weekly_minutes: null,
  status: "not_started",
  current_step: 1,
  revision: 1,
  updated_at: "2026-09-11T00:00:00Z",
  next_action_href: "/onboarding",
  next_action_reason: "profile_not_started",
};
const program: ProgramDetailResponse = {
  id: "course-intent-program",
  slug: course,
  title: "Published free course fixture",
  program_version_id: "course-intent-version",
  version_number: 1,
  published_at: "2026-09-11T00:00:00Z",
  modules: [],
};

describe("mounted course and activity navigation recovery", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
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
  });
  it.each(
    (
      [
        "completed",
        "skipped",
        "not_started",
        "in_progress",
        "unavailable",
      ] as const
    ).flatMap((status) =>
      [null, activity].map((activityIntent) => ({ status, activityIntent })),
    ),
  )(
    "awaits password login before onboarding $status with activity $activityIntent",
    async ({ status, activityIntent }) => {
      let completeLogin!: () => void;
      const loginPassword = vi.fn(
        () =>
          new Promise<void>((resolve) => {
            completeLogin = resolve;
          }),
      );
      const onboarding = vi.fn(async () => {
        if (status === "unavailable") throw new ApiError(503, "Unavailable");
        return { ...profile, status };
      });
      vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
        loginPassword,
        onboarding,
      } as unknown as LearnerApi);
      const navigate = vi
        .spyOn(window.location, "assign")
        .mockImplementation(() => {});
      await act(async () =>
        root.render(
          <LoginForm courseIntent={course} activityIntent={activityIntent} />,
        ),
      );
      container.querySelector<HTMLInputElement>("#login-email")!.value =
        "learner@example.test";
      container.querySelector<HTMLInputElement>("#login-password")!.value =
        "synthetic-test-password";
      await act(async () =>
        container
          .querySelector("form")!
          .dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      expect(loginPassword).toHaveBeenCalledExactlyOnceWith(
        "learner@example.test",
        "synthetic-test-password",
      );
      expect(onboarding).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
      await act(async () => completeLogin());
      expect(onboarding).toHaveBeenCalledTimes(1);
      expect(loginPassword.mock.invocationCallOrder[0]).toBeLessThan(
        onboarding.mock.invocationCallOrder[0],
      );
      const onboardingComplete = status === "completed" || status === "skipped";
      const target = onboardingComplete
        ? activityIntent
          ? activityHref
          : "/home?course=" + course
        : "/onboarding?course=" +
          course +
          (activityIntent ? "&activity=" + activity : "");
      expect(navigate).toHaveBeenCalledExactlyOnceWith(target);
    },
  );
  it.each([401, 503])(
    "does not read onboarding or navigate after password failure %s",
    async (status) => {
      const loginPassword = vi.fn(async () => {
        throw new ApiError(status, "Sign-in unavailable");
      });
      const onboarding = vi.fn(async () => profile);
      vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
        loginPassword,
        onboarding,
      } as unknown as LearnerApi);
      const navigate = vi
        .spyOn(window.location, "assign")
        .mockImplementation(() => {});
      await act(async () =>
        root.render(
          <LoginForm courseIntent={course} activityIntent={activity} />,
        ),
      );
      container.querySelector<HTMLInputElement>("#login-email")!.value =
        "learner@example.test";
      container.querySelector<HTMLInputElement>("#login-password")!.value =
        "synthetic-test-password";
      await act(async () =>
        container
          .querySelector("form")!
          .dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      expect(loginPassword).toHaveBeenCalledTimes(1);
      expect(onboarding).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
      expect(container.querySelector('[role="alert"]')?.textContent).toContain(
        "Sign-in could not be completed",
      );
    },
  );
  it.each(
    (["skipped", "completed"] as const).flatMap((status) =>
      [
        {
          name: "course only",
          activityIntent: null,
          returnHref: undefined,
          href: "/home?course=" + course,
          label: "Open learner home",
        },
        {
          name: "course and activity",
          activityIntent: activity,
          returnHref: undefined,
          href: activityHref,
          label: "Resume activity",
        },
        {
          name: "settings precedence",
          activityIntent: activity,
          returnHref: "/settings",
          href: "/settings",
          label: "Return to settings",
        },
      ].map((destination) => ({ status, ...destination })),
    ),
  )(
    "returns to $name after the actual $status onboarding action",
    async ({ status, activityIntent, returnHref, href, label }) => {
      const initialProfile: OnboardingResponse =
        status === "completed"
          ? {
              ...profile,
              status: "in_progress",
              current_step: 3,
              experience_context: "sales",
              learning_goal: "Run clearer discovery calls",
              practice_situation: "A discovery call to prepare for",
              weekly_minutes: 30,
            }
          : profile;
      const saveOnboarding = vi.fn(async () => ({
        ...initialProfile,
        status,
        revision: 2,
        next_action_href: "/home",
      }));
      const api = {
        onboarding: vi.fn(async () => initialProfile),
        saveOnboarding,
      } as unknown as LearnerApi;
      await act(async () =>
        root.render(
          <OnboardingForm
            api={api}
            initialProfile={initialProfile}
            courseIntent={course}
            activityIntent={activityIntent}
            returnHref={returnHref}
          />,
        ),
      );
      const action = [...container.querySelectorAll("button")].find(
        (button) =>
          button.textContent?.trim() ===
          (status === "skipped" ? "Skip setup" : "Save profile"),
      );
      expect(action).toBeDefined();
      expect(action!.disabled).toBe(false);
      await act(async () => action!.click());
      expect(saveOnboarding).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({
          status,
          currentStep: initialProfile.current_step,
        }),
        initialProfile.revision,
      );
      const continuation = container.querySelector(".onboarding-complete a");
      expect(continuation?.getAttribute("href")).toBe(href);
      expect(continuation?.textContent?.trim()).toBe(label);
    },
  );
  it("connects all five public free-course auth actions without calling enrollment", async () => {
    const enrollFree = vi.fn();
    const api = {
      program: vi.fn(async () => program),
      enrollFree,
    } as unknown as LearnerApi;
    await act(async () =>
      root.render(<PublicProgramDetail slug={course} api={api} />),
    );
    const links = [
      ...container.querySelectorAll<HTMLAnchorElement>(
        'a[href^="/login"], a[href^="/register"]',
      ),
    ];
    expect(links).toHaveLength(5);
    for (const link of links)
      expect(new URL(link.href).searchParams.getAll("course")).toEqual([
        course,
      ]);
    expect(enrollFree).not.toHaveBeenCalled();
  });
  it.each(recoveryCases)(
    "preserves $name when the initial onboarding read requires a fresh session",
    async ({ activityIntent, returnHref, href }) => {
      const api = {
        onboarding: vi.fn(async () => {
          throw new ApiError(401, "Session expired");
        }),
      } as unknown as LearnerApi;
      await act(async () =>
        root.render(
          <OnboardingForm
            api={api}
            courseIntent={course}
            activityIntent={activityIntent}
            returnHref={returnHref}
          />,
        ),
      );
      const recovery = [...container.querySelectorAll("a")].find(
        (link) => link.textContent?.trim() === "Sign in again",
      );
      expect(recovery?.getAttribute("href")).toBe(href);
    },
  );
  it.each(recoveryCases)(
    "preserves $name after a save requires a fresh session",
    async ({ activityIntent, returnHref, href }) => {
      const saveOnboarding = vi.fn(async () => {
        throw new ApiError(401, "Session expired");
      });
      const api = {
        onboarding: vi.fn(async () => profile),
        saveOnboarding,
      } as unknown as LearnerApi;
      await act(async () =>
        root.render(
          <OnboardingForm
            api={api}
            initialProfile={profile}
            courseIntent={course}
            activityIntent={activityIntent}
            returnHref={returnHref}
          />,
        ),
      );
      const skip = [...container.querySelectorAll("button")].find(
        (button) => button.textContent === "Skip setup",
      );
      expect(skip).toBeDefined();
      await act(async () => skip!.click());
      expect(saveOnboarding).toHaveBeenCalledTimes(1);
      const recovery = [...container.querySelectorAll("a")].find(
        (link) => link.textContent?.trim() === "Sign in again",
      );
      expect(recovery?.getAttribute("href")).toBe(href);
    },
  );
});
