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

describe("mounted course navigation recovery", () => {
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
  it.each([
    "completed",
    "skipped",
    "not_started",
    "in_progress",
    "unavailable",
  ] as const)(
    "submits password login before routing through canonical onboarding %s",
    async (status) => {
      const loginPassword = vi.fn(async () => undefined);
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
      await act(async () => root.render(<LoginForm courseIntent={course} />));
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
      expect(onboarding).toHaveBeenCalledTimes(1);
      expect(loginPassword.mock.invocationCallOrder[0]).toBeLessThan(
        onboarding.mock.invocationCallOrder[0],
      );
      const target =
        status === "completed" || status === "skipped"
          ? "/home"
          : "/onboarding";
      expect(navigate).toHaveBeenCalledExactlyOnceWith(
        target + "?course=" + course,
      );
    },
  );
  it("keeps the course on the actual completed skip-setup action", async () => {
    const saveOnboarding = vi.fn(async () => ({
      ...profile,
      status: "skipped",
      current_step: 1,
      revision: 2,
      next_action_href: "/home",
    }));
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
        />,
      ),
    );
    const skip = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Skip setup",
    );
    expect(skip).toBeDefined();
    await act(async () => skip!.click());
    expect(saveOnboarding).toHaveBeenCalledWith(
      expect.objectContaining({ status: "skipped" }),
      profile.revision,
    );
    expect(
      container.querySelector('a[href="/home?course=' + course + '"]')
        ?.textContent,
    ).toContain("Open learner home");
  });
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
  it("retains the course when the initial onboarding read requires a fresh session", async () => {
    const api = {
      onboarding: vi.fn(async () => {
        throw new ApiError(401, "Session expired");
      }),
    } as unknown as LearnerApi;
    await act(async () =>
      root.render(<OnboardingForm api={api} courseIntent={course} />),
    );
    expect(
      container.querySelector(
        'a[href="/session-expired?course=' + course + '"]',
      ),
    ).not.toBeNull();
  });
  it("retains the course after a save requires a fresh session", async () => {
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
        />,
      ),
    );
    const skip = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Skip setup",
    );
    expect(skip).toBeDefined();
    await act(async () => skip!.click());
    expect(saveOnboarding).toHaveBeenCalledTimes(1);
    expect(
      container.querySelector(
        'a[href="/session-expired?course=' + course + '"]',
      ),
    ).not.toBeNull();
  });
});
