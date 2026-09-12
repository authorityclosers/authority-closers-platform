// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CalendarResponse,
  type LearnerApi,
  type LearningResponse,
  type MeResponse,
  type OnboardingResponse,
  type ProgramSummaryResponse,
} from "../lib/learner-api";
import { DashboardRuntime, loadDashboardData } from "./dashboard-runtime";
import { FREE_COURSE_SLUG, type CourseIntent } from "../lib/course-intent";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const me: MeResponse = {
  person_id: "person-dashboard",
  email: "learner@example.com",
  display_name: "Dashboard learner",
  email_verified_at: "2026-09-07T00:00:00Z",
  selected_tenant_id: "tenant-dashboard",
  membership_role: "learner",
  permissions: [],
};

const onboarding: OnboardingResponse = {
  person_id: me.person_id,
  experience_context: null,
  learning_goal: null,
  practice_situation: null,
  weekly_minutes: null,
  status: "completed",
  current_step: 4,
  revision: 1,
  updated_at: "2026-09-07T00:00:00Z",
  next_action_href: "/home",
  next_action_reason: "profile_complete",
};

const program: ProgramSummaryResponse = {
  id: "program-dashboard",
  slug: "authority-closers-free-course",
  title: "Published dashboard fixture",
  program_version_id: "version-dashboard",
  version_number: 1,
  published_at: "2026-09-07T00:00:00Z",
};

const learning: LearningResponse = {
  program_id: program.id,
  program_slug: program.slug,
  program_title: program.title,
  program_version_id: program.program_version_id,
  version_number: 1,
  enrollment_id: "enrollment-dashboard",
  modules: [
    {
      id: "module-dashboard",
      position: 1,
      title: "Published module",
      activities: [
        {
          id: "activity-dashboard",
          module_id: "module-dashboard",
          program_version_id: program.program_version_id,
          position: 1,
          kind: "REFLECTION",
          title: "Published reflection",
          prompt: null,
          state: "available",
          revision: 1,
          required: true,
          allowed_actions: ["save_draft"],
          explanation: {
            activity_id: "activity-dashboard",
            state: "available",
            required: true,
            reason: "Ready",
            missing_activity_ids: [],
            missing_module_ids: [],
          },
        },
      ],
    },
  ],
  projection: {
    scope_type: "program",
    scope_id: program.id,
    program_version: program.program_version_id,
    projection_version: "v1",
    denominator: 1,
    completed_count: 0,
    percentage: 0,
    predicate: "required_activities_complete",
    missing_module_ids: [],
    activity_reasons: [],
  },
};

function calendar(
  title = "Current tenant plan",
  tenantId = me.selected_tenant_id!,
): CalendarResponse {
  return {
    source: "explicit_learning_plan",
    disclaimer: "Synthetic presentation fixture.",
    periods: {
      today: {
        period: "today",
        status: "available",
        source: "explicit_learning_plan",
        message: null,
        items: [
          {
            id: title,
            tenant_id: tenantId,
            person_id: me.person_id,
            period: "today",
            title,
            activity_id: "activity-dashboard",
            planned_for: null,
            state: "planned",
            source: "explicit_learning_plan",
          },
        ],
      },
      week: {
        period: "week",
        status: "not_configured",
        source: "explicit_learning_plan",
        message: null,
        items: [],
      },
      month: {
        period: "month",
        status: "not_configured",
        source: "explicit_learning_plan",
        message: null,
        items: [],
      },
    },
  };
}

function apiFor(overrides: Partial<LearnerApi> = {}): LearnerApi {
  return {
    me: vi.fn(async () => me),
    onboarding: vi.fn(async () => onboarding),
    listPrograms: vi.fn(async () => ({ items: [program], next_cursor: null })),
    learning: vi.fn(async () => learning),
    calendar: vi.fn(async () => calendar()),
    ...overrides,
  } as unknown as LearnerApi;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolveValue, rejectValue) => {
    resolve = resolveValue;
    reject = rejectValue;
  });
  return { promise, resolve, reject };
}

describe("mounted dashboard progressive plan", () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  async function mount(api: LearnerApi, courseIntent: CourseIntent = null) {
    await act(async () =>
      root.render(<DashboardRuntime api={api} courseIntent={courseIntent} />),
    );
  }

  it("preserves course intent while required onboarding prevents catalog and enrollment reads", async () => {
    const navigate = vi
      .spyOn(window.location, "replace")
      .mockImplementation(() => {});
    const enrollFree = vi.fn();
    const api = apiFor({
      onboarding: vi.fn(async () => ({
        ...onboarding,
        status: "not_started" as const,
      })),
      enrollFree,
    });
    await mount(api, FREE_COURSE_SLUG);
    expect(navigate).toHaveBeenCalledWith(
      "/onboarding?course=" + FREE_COURSE_SLUG,
    );
    expect(api.listPrograms).not.toHaveBeenCalled();
    expect(api.learning).not.toHaveBeenCalled();
    expect(api.calendar).not.toHaveBeenCalled();
    expect(enrollFree).not.toHaveBeenCalled();
  });

  it("requires an explicit enrollment action even with a valid course intent", async () => {
    const enrollFree = vi.fn();
    const api = apiFor({
      learning: vi.fn(async () => {
        throw new ApiError(404, "No enrollment");
      }),
      enrollFree,
    });
    await mount(api, FREE_COURSE_SLUG);
    expect(container.textContent).toContain("Start the Free Course");
    expect(enrollFree).not.toHaveBeenCalled();
  });

  it("renders the primary action while calendar is pending after onboarding", async () => {
    const setup = deferred<OnboardingResponse>();
    const plan = deferred<CalendarResponse>();
    const api = apiFor({
      onboarding: vi.fn(() => setup.promise),
      calendar: vi.fn(() => plan.promise),
    });
    await mount(api);
    expect(api.listPrograms).not.toHaveBeenCalled();
    expect(api.calendar).not.toHaveBeenCalled();
    expect(container.querySelector("#dashboard-title")).toBeNull();

    await act(async () => setup.resolve(onboarding));

    expect(container.querySelector("#dashboard-title")?.textContent).toContain(
      "Dashboard learner",
    );
    const primary = container.querySelector<HTMLAnchorElement>(
      ".continue-lesson-link",
    );
    expect(primary?.textContent).toContain("Continue activity");
    expect(primary?.getAttribute("href")).toBe("/activity/activity-dashboard");
    expect(container.textContent).not.toContain("Continue watching");
    expect(container.textContent).not.toContain("Your weekly activity");
    expect(container.textContent).not.toContain(
      "Approved lesson media is not connected",
    );
    expect(
      container.querySelector(".ac-media-frame__art")?.getAttribute("src"),
    ).toContain("instructor-v2%2Ffront-facing.jpeg");
    const editorial = container.querySelector(".ac-media-frame");
    expect(editorial?.textContent).toContain("Learn with Dipak");
    expect(editorial?.textContent).not.toContain("Published reflection");
    expect(editorial?.querySelector("img")?.getAttribute("alt")).toBe("");
    expect(editorial?.querySelector("video, iframe, button")).toBeNull();
    expect(container.querySelector(".ac-continue-meta h3")?.textContent).toBe(
      "Published reflection",
    );
    const planPanel = container.querySelector(".todays-plan-card");
    expect(planPanel?.getAttribute("aria-busy")).toBe("true");
    expect(planPanel?.textContent).toContain("Loading today's plan");
    expect(planPanel?.textContent).not.toContain("No explicit plan");
    const signal = vi.mocked(api.me).mock.calls[0][0]?.signal;
    expect(api.calendar).toHaveBeenCalledWith({ signal });
    expect(signal?.aborted).toBe(false);

    await act(async () => plan.resolve(calendar()));

    expect(planPanel?.getAttribute("aria-busy")).toBe("false");
    expect(planPanel?.textContent).toContain("Current tenant plan");
    expect(container.querySelector(".continue-lesson-link")).toBe(primary);
  });

  it("confines an optional plan failure to its panel", async () => {
    const plan = deferred<CalendarResponse>();
    await mount(apiFor({ calendar: vi.fn(() => plan.promise) }));
    await act(async () => plan.reject(new ApiError(503, "Plan unavailable")));

    expect(container.querySelector("#dashboard-title")).not.toBeNull();
    expect(container.querySelector(".continue-lesson-link")).not.toBeNull();
    expect(container.querySelector(".todays-plan-card")?.textContent).toContain(
      "Plan unavailable",
    );
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it.each([null, FREE_COURSE_SLUG] as const)(
    "requires session recovery without losing course %s when the current plan returns 401",
    async (courseIntent) => {
      const plan = deferred<CalendarResponse>();
      await mount(
        apiFor({ calendar: vi.fn(() => plan.promise) }),
        courseIntent,
      );
      expect(container.querySelector("#dashboard-title")).not.toBeNull();

      await act(async () => plan.reject(new ApiError(401, "Session expired")));

      expect(container.querySelector("#dashboard-title")).toBeNull();
      expect(container.querySelector('[role="alert"]')?.textContent).toContain(
        "Sign in to continue",
      );
      expect(
        container.querySelector(
          'a[href="/session-expired' +
            (courseIntent ? "?course=" + courseIntent : "") +
            '"]',
        ),
      ).not.toBeNull();
    },
  );

  it.each(["success", "401"])(
    "ignores a superseded tenant plan %s even if the API ignores abort",
    async (outcome) => {
      const stale = deferred<CalendarResponse>();
      const oldApi = apiFor({ calendar: vi.fn(() => stale.promise) });
      await mount(oldApi);
      const oldSignal = vi.mocked(oldApi.calendar).mock.calls[0][0]?.signal;

      await mount(
        apiFor({
          me: vi.fn(async () => ({
            ...me,
            selected_tenant_id: "tenant-new",
            display_name: "New tenant learner",
          })),
          calendar: vi.fn(async () =>
            calendar("New tenant plan", "tenant-new"),
          ),
        }),
      );
      expect(oldSignal?.aborted).toBe(true);
      await act(async () => {
        if (outcome === "success") stale.resolve(calendar("Stale tenant plan"));
        else stale.reject(new ApiError(401, "Old session expired"));
      });

      expect(
        container.querySelector("#dashboard-title")?.textContent,
      ).toContain("New tenant learner");
      expect(
        container.querySelector(".todays-plan-card")?.textContent,
      ).toContain("New tenant plan");
      expect(container.textContent).not.toContain("Stale tenant plan");
      expect(container.querySelector('[role="alert"]')).toBeNull();
    },
  );

  it("aborts pending work on unmount and ignores its later completion", async () => {
    const plan = deferred<CalendarResponse>();
    const api = apiFor({ calendar: vi.fn(() => plan.promise) });
    await mount(api);
    const signal = vi.mocked(api.calendar).mock.calls[0][0]?.signal;
    await act(async () => root.render(null));
    expect(signal?.aborted).toBe(true);
    await act(async () => plan.resolve(calendar("Unmounted plan")));
    expect(container.childElementCount).toBe(0);
  });
});

describe("complete dashboard loader compatibility", () => {
  it("returns the settled calendar for callers requesting the complete read", async () => {
    const controller = new AbortController();
    const api = apiFor();
    const result = await loadDashboardData(api, controller.signal);
    expect(result).toMatchObject({
      kind: "ready",
      data: { calendar: calendar(), calendarStatus: "available" },
    });
    expect(api.calendar).toHaveBeenCalledWith({ signal: controller.signal });
  });

  it("does not read catalog or calendar before required onboarding completes", async () => {
    const api = apiFor({
      onboarding: vi.fn(async () => ({
        ...onboarding,
        status: "in_progress" as const,
      })),
    });
    await expect(loadDashboardData(api)).resolves.toEqual({
      kind: "onboarding",
    });
    expect(api.listPrograms).not.toHaveBeenCalled();
    expect(api.calendar).not.toHaveBeenCalled();
  });

  it("does not request a plan without a selected tenant", async () => {
    const api = apiFor({
      me: vi.fn(async () => ({ ...me, selected_tenant_id: null })),
    });
    await expect(loadDashboardData(api)).resolves.toMatchObject({
      kind: "ready",
      data: { calendarStatus: "not_configured" },
    });
    expect(api.calendar).not.toHaveBeenCalled();
  });
});
