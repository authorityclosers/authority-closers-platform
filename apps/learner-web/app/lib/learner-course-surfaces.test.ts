import { readFileSync } from "node:fs";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ActivityRow,
  ModuleCard,
  NextActionCard,
  ProgramCard,
  RouteHeader,
  StatusBanner,
} from "@ac/ui";
import { loadDiscoverData } from "../components/discover-runtime";
import {
  getCourseNextAction,
  getCourseProjection,
  LearningCourseCard,
} from "../components/learning-course-card";
import {
  filterLearningCourses,
  getLearningFilterKeyboardTarget,
  getLearningLoadErrorClass,
  getLearningLoadErrorPresentation,
  LearningLoadErrorState,
  LearningFilterTabs,
  loadLearningData,
} from "../components/learning-runtime";
import DiscoverPage from "../discover/page";
import LearningPage from "../learning/page";
import {
  ApiError,
  type LearnerApi,
  type LearningCourseSummaryResponse,
} from "./learner-api";
import { getOfflineReadMetadata, markOfflineRead } from "./offline-read-cache";

describe("learner course surface primitives", () => {
  it("keeps route headers semantic and card titles scoped", () => {
    const header = renderToStaticMarkup(
      createElement(RouteHeader, {
        title: "Discover Programs",
        titleId: "discover-title",
        breadcrumbs: createElement("span", null, "Dashboard / Discover"),
        description: "Published programs from the catalog.",
      }),
    );
    const card = renderToStaticMarkup(
      createElement(ProgramCard, {
        title: "Published course",
        titleId: "published-course",
        titleAs: "h3",
        description: "Published 9/1/2026 · Version 1",
        action: createElement(
          "a",
          { href: "/programs/published-course" },
          "View program",
        ),
      }),
    );

    expect(header).toContain('<h1 id="discover-title"');
    expect(header).toContain("Published programs from the catalog.");
    expect(card).toContain('<h3 id="published-course"');
    expect(card).toContain('href="/programs/published-course"');
  });

  it("makes state, next-action, module, and activity boundaries explicit", () => {
    const errorProps = {
      state: "error" as const,
      title: "Catalog unavailable",
    } as ComponentProps<typeof StatusBanner>;
    errorProps.children = createElement("p", null, "Retry the catalog read.");
    const error = renderToStaticMarkup(createElement(StatusBanner, errorProps));
    const next = renderToStaticMarkup(
      createElement(NextActionCard, {
        eyebrow: "Next action",
        title: "Reflect on the signal",
        detail: "Open the server-authorized activity.",
        action: createElement(
          "a",
          { href: "/activity/reflection-1" },
          "Open activity",
        ),
      }),
    );
    const moduleCard = renderToStaticMarkup(
      createElement(
        ModuleCard,
        {
          title: "Module 1",
          titleId: "module-1-title",
          position: "Module 1",
          status: "Available",
        },
        createElement("p", null, "Ordered activities"),
      ),
    );
    const activeRow = renderToStaticMarkup(
      createElement(ActivityRow, {
        position: "01",
        title: "Reflect on the signal",
        href: "/activity/reflection-1",
        ariaLabel: "1. Reflect on the signal, Available",
        status: "Available",
      }),
    );
    const lockedRow = renderToStaticMarkup(
      createElement(ActivityRow, {
        position: "02",
        title: "Locked review",
        href: "/activity/locked-review",
        ariaLabel: "2. Locked review, Locked",
        disabled: true,
        status: "Locked",
      }),
    );

    expect(error).toContain('role="alert"');
    expect(error).toContain("Catalog unavailable");
    expect(next).toContain("Next action");
    expect(next).toContain('href="/activity/reflection-1"');
    expect(moduleCard).toContain('aria-labelledby="module-1-title"');
    expect(activeRow).toContain('href="/activity/reflection-1"');
    expect(lockedRow).toContain('aria-disabled="true"');
    expect(lockedRow).not.toContain('href="/activity/locked-review"');
  });

  it("gives every canonical course state one safe, state-based next action", () => {
    const baseCourse: LearningCourseSummaryResponse = {
      program_id: "program-1",
      program_version_id: "version-1",
      program_slug: "course-one",
      program_title: "Course One",
      version_number: 1,
      enrollment_id: "enrollment-1",
      enrolled_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
      state: "in_progress",
      saved_state: "saved",
      projection: {
        scope_type: "course",
        scope_id: "program-1",
        program_version: "1",
        projection_version: "1",
        denominator: 4,
        completed_count: 1,
        percentage: 0.25,
        predicate: "required activities",
        missing_module_ids: [],
        activity_reasons: [],
      },
    };

    expect(getCourseNextAction("in_progress").id).toBe("continue");
    expect(getCourseNextAction("completed").id).toBe("review");
    expect(getCourseNextAction("unavailable").id).toBe("open");
    expect(getCourseProjection(baseCourse)).toEqual({
      value: 25,
      detail: "1 of 4 required activities",
    });

    const inProgress = renderToStaticMarkup(
      createElement(LearningCourseCard, { course: baseCourse, index: 0 }),
    );
    const completed = renderToStaticMarkup(
      createElement(LearningCourseCard, {
        course: { ...baseCourse, state: "completed" },
        index: 1,
      }),
    );
    const unavailable = renderToStaticMarkup(
      createElement(LearningCourseCard, {
        course: { ...baseCourse, state: "unavailable", projection: null },
        index: 2,
      }),
    );

    expect(inProgress).toContain("Continue course");
    expect(inProgress).toContain('data-next-action="continue"');
    expect(inProgress).toContain('href="/learn/course-one"');
    expect(inProgress).toContain("Saved");
    expect(completed).toContain("Review course");
    expect(completed).toContain('data-next-action="review"');
    expect(unavailable).toContain("Open course");
    expect(unavailable).toContain("Progress unavailable");
    expect(unavailable).toContain("re-check current access");
    expect(unavailable).toContain('data-next-action="open"');
    expect(unavailable).not.toContain('href="/activity/');
    expect(unavailable).not.toContain("LockKeyhole");
    expect(unavailable).not.toContain("Locked");
  });

  it("associates the filter tabs with their panel and supports roving keyboard movement", () => {
    const tabs = renderToStaticMarkup(
      createElement(LearningFilterTabs, {
        filter: "in_progress",
        savedFilterAvailable: false,
        onFilterChange: () => undefined,
      }),
    );

    expect(tabs).toContain('role="tablist"');
    expect(tabs).toContain('aria-orientation="horizontal"');
    expect(tabs).toContain('id="learning-filter-in_progress"');
    expect(tabs).toContain('aria-controls="learning-course-list"');
    expect(tabs).toContain('aria-selected="true"');
    expect(tabs).toContain('tabindex="0"');
    expect(tabs).toContain('tabindex="-1"');
    expect(getLearningFilterKeyboardTarget("all", "ArrowRight", true)).toBe(
      "in_progress",
    );
    expect(
      getLearningFilterKeyboardTarget("completed", "ArrowRight", false),
    ).toBe("all");
    expect(getLearningFilterKeyboardTarget("all", "End", true)).toBe("saved");
    expect(getLearningFilterKeyboardTarget("all", "ArrowRight", false)).toBe(
      "in_progress",
    );
  });

  it("follows collection cursors across pages and exposes offline provenance", async () => {
    const me = {
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: "tenant-1",
      membership_role: "learner",
      permissions: ["learner:read"],
    };
    const firstPage = markOfflineRead(
      {
        items: [],
        next_cursor: "cursor-2",
        saved_filter_available: true,
      },
      1_100,
    );
    const secondPage = markOfflineRead(
      {
        items: [],
        next_cursor: null,
        saved_filter_available: true,
      },
      1_200,
    );
    const cursors: Array<string | undefined> = [];
    const api = {
      me: async () => me,
      learningCollection: async (
        limit: number,
        options?: { cursor?: string },
      ) => {
        expect(limit).toBe(50);
        cursors.push(options?.cursor);
        return cursors.length === 1 ? firstPage : secondPage;
      },
    } as unknown as LearnerApi;

    const result = await loadLearningData(api);

    expect(cursors).toEqual([undefined, "cursor-2"]);
    expect(result.courses).toEqual([]);
    expect(result.savedFilterAvailable).toBe(true);
    expect(getOfflineReadMetadata(result.me)).toBeNull();
    expect(result.offlineRead).toEqual({
      isOfflineCopy: true,
      savedAt: 1_100,
    });
  });

  it("keeps filter transitions derived from the canonical collection fields", () => {
    const course = (
      state: "in_progress" | "completed",
      saved_state: "saved" | "unavailable",
    ) =>
      ({
        program_id: `${state}-${saved_state}`,
        program_version_id: "version-1",
        program_slug: `${state}-${saved_state}`,
        program_title: "Course",
        version_number: 1,
        enrollment_id: "enrollment-1",
        enrolled_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
        state,
        saved_state,
        projection: null,
      }) as LearningCourseSummaryResponse;
    const courses = [
      course("in_progress", "saved"),
      course("completed", "unavailable"),
    ];

    expect(filterLearningCourses(courses, "all", true)).toHaveLength(2);
    expect(filterLearningCourses(courses, "in_progress", true)).toHaveLength(1);
    expect(filterLearningCourses(courses, "completed", true)).toHaveLength(1);
    expect(filterLearningCourses(courses, "saved", true)).toHaveLength(1);
    expect(filterLearningCourses(courses, "saved", false)).toHaveLength(0);
  });

  it("classifies retryable statuses and network failures while keeping terminal errors distinct", () => {
    for (const status of [408, 425, 429, 500, 503, 599]) {
      expect(getLearningLoadErrorClass(new ApiError(status, "temporary"))).toBe(
        "retryable",
      );
    }
    expect(getLearningLoadErrorClass(new TypeError("offline"))).toBe(
      "retryable",
    );
    for (const status of [400, 401, 403, 404, 499]) {
      expect(getLearningLoadErrorClass(new ApiError(status, "terminal"))).toBe(
        "terminal",
      );
    }
    expect(getLearningLoadErrorClass(new Error("invalid response"))).toBe(
      "terminal",
    );

    expect(getLearningLoadErrorPresentation(new TypeError("offline"))).toEqual({
      errorClass: "retryable",
      title: "Learning library is temporarily unavailable",
      detail:
        "The learning service or network is temporarily unavailable. Retry the read; no learner work was changed.",
      requiresSignIn: false,
      requiresSupport: false,
      supportHref: null,
      canRetry: true,
    });
    expect(
      getLearningLoadErrorPresentation(new ApiError(401, "expired")),
    ).toEqual({
      errorClass: "terminal",
      title: "Sign in to view your learning",
      detail: "Your session has expired. Sign in again to view your courses.",
      requiresSignIn: true,
      requiresSupport: false,
      supportHref: null,
      canRetry: false,
    });
    expect(
      getLearningLoadErrorPresentation(new ApiError(403, "denied")),
    ).toEqual({
      errorClass: "terminal",
      title: "You do not have access to this learner library",
      detail:
        "This account is not authorized to view this learner library. If you think this is incorrect, contact support.",
      requiresSignIn: false,
      requiresSupport: true,
      supportHref:
        "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20learner%20access",
      canRetry: false,
    });
    const forbiddenMarkup = renderToStaticMarkup(
      createElement(LearningLoadErrorState, {
        presentation: getLearningLoadErrorPresentation(
          new ApiError(403, "denied"),
        ),
        onRetry: () => undefined,
      }),
    );
    expect(forbiddenMarkup).toContain(
      'href="mailto:admin@authorityclosers.com?subject=Authority%20Closers%20learner%20access"',
    );
    expect(forbiddenMarkup).toContain("Contact learner support");
    expect(forbiddenMarkup).not.toContain(">Retry<");
    expect(
      getLearningLoadErrorPresentation(new ApiError(404, "not found")),
    ).toEqual({
      errorClass: "terminal",
      title: "Could not load your courses",
      detail: "not found",
      requiresSignIn: false,
      requiresSupport: false,
      supportHref: null,
      canRetry: false,
    });
  });
});

describe("learner course route wiring", () => {
  it("keeps Discover read-only and leaves free enrollment on Home", async () => {
    const calls: string[] = [];
    const api = {
      me: async () => {
        calls.push("me");
        return {
          person_id: "person-1",
          email: "learner@example.com",
          display_name: "Learner",
          email_verified_at: "2026-09-01T00:00:00Z",
          selected_tenant_id: "tenant-1",
          membership_role: "learner",
          permissions: [],
        };
      },
      listPrograms: async () => {
        calls.push("programs");
        return {
          items: [
            {
              id: "program-1",
              slug: "authority-closers-free-course",
              title: "Authority Closers Free Course",
              program_version_id: "version-1",
              version_number: 1,
              published_at: "2026-09-01T00:00:00Z",
            },
          ],
          next_cursor: null,
        };
      },
      learning: async () => {
        calls.push("learning");
        throw new ApiError(404, "No enrollment");
      },
      enrollFree: async () => {
        calls.push("enroll");
        throw new Error("Discover must not call enrollment");
      },
    } as unknown as Parameters<typeof loadDiscoverData>[0];

    const result = await loadDiscoverData(api, undefined, false);

    expect(result.programs).toHaveLength(1);
    expect(result.learning).toBeNull();
    expect(calls).toEqual(["me", "programs", "learning"]);
    expect(calls).not.toContain("enroll");
  });

  it("keeps the bounded loading routes route-shaped", async () => {
    const discover = renderToStaticMarkup(
      await DiscoverPage({
        searchParams: Promise.resolve({ state: "LOADING" }),
      }),
    );
    const learning = renderToStaticMarkup(
      await LearningPage({
        searchParams: Promise.resolve({ state: "LOADING" }),
      }),
    );

    expect(discover).toContain("discover-skeleton");
    expect(discover).toContain("Discover Programs");
    expect(learning).toContain("learning-skeleton");
    expect(learning).toContain("My Learning");
  });

  it("keeps responsive/PWA and reduced-motion contracts in the surface layer", () => {
    const css = readFileSync(
      new URL("../course-surfaces.css", import.meta.url),
      "utf8",
    );

    expect(css).toContain("@media (max-width: 900px)");
    expect(css).toContain("@media (max-width: 560px)");
    expect(css).toContain("@media (display-mode: standalone)");
    expect(css).toContain("env(safe-area-inset-bottom)");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toContain(".site-frame--learner .skeleton-line");
    expect(css).toContain("max-width: 100%");
    expect(css).toContain("min-height: 44px");
  });
});
