import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  buildAllLearningRollup,
  ProgressMotivationPanel,
  ProgressScopePanel,
} from "../components/progress-momentum";
import {
  loadProgressData,
  shouldIgnoreProgressLoadError,
} from "../components/progress-runtime";
import { ApiError } from "./learner-api";
import type {
  LearnerApi,
  LearningCollectionResponse,
  LearningResponse,
  MeResponse,
  ProgramSummaryResponse,
} from "./learner-api";
import { markOfflineRead } from "./offline-read-cache";

const projection = {
  scope_type: "program_version",
  scope_id: "program-version-1",
  program_version: "1.0.0",
  projection_version: "progress-v1",
  denominator: 10,
  completed_count: 4,
  percentage: 0.4,
  predicate: "required activities completed",
  missing_module_ids: [],
  activity_reasons: [],
};

const learning: LearningResponse = {
  program_id: "program-1",
  program_version_id: "program-version-1",
  program_slug: "authority-closers-free-course",
  program_title: "Authority Closers Foundations",
  version_number: 1,
  enrollment_id: "enrollment-1",
  modules: [],
  projection,
};

const me: MeResponse = {
  person_id: "person-1",
  email: "learner@example.com",
  display_name: "Learner",
  email_verified_at: "2026-09-01T00:00:00Z",
  selected_tenant_id: "tenant-1",
  membership_role: "learner",
  permissions: [],
};

const freeProgram: ProgramSummaryResponse = {
  id: learning.program_id,
  slug: learning.program_slug,
  title: learning.program_title,
  program_version_id: learning.program_version_id,
  version_number: learning.version_number,
  published_at: "2026-09-01T00:00:00Z",
};

const collection: LearningCollectionResponse = {
  items: [
    {
      program_id: learning.program_id,
      program_version_id: learning.program_version_id,
      program_slug: learning.program_slug,
      program_title: learning.program_title,
      version_number: learning.version_number,
      enrollment_id: learning.enrollment_id,
      enrolled_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-03T00:00:00Z",
      state: "in_progress",
      saved_state: "unavailable",
      projection,
    },
    {
      program_id: "program-2",
      program_version_id: "program-version-2",
      program_slug: "authority-closers-practice",
      program_title: "Authority Closers Practice",
      version_number: 2,
      enrollment_id: "enrollment-2",
      enrolled_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-09-02T00:00:00Z",
      state: "completed",
      saved_state: "saved",
      projection: {
        ...projection,
        scope_id: "program-version-2",
        denominator: 6,
        completed_count: 6,
        percentage: 1,
      },
    },
  ],
  next_cursor: null,
  saved_filter_available: true,
};

function progressApi(
  learningCollection: LearnerApi["learningCollection"],
): LearnerApi {
  return {
    me: vi.fn(async () => me),
    listPrograms: vi.fn(async () => ({
      items: [freeProgram],
      next_cursor: null,
    })),
    learning: vi.fn(async () => learning),
    learningCollection,
  } as unknown as LearnerApi;
}

describe("learner progress motivation foundations", () => {
  it("rolls up only returned canonical course projections", () => {
    expect(buildAllLearningRollup(collection)).toEqual({
      status: "available",
      courseCount: 2,
      completedCourseCount: 1,
      completedActivities: 10,
      requiredActivities: 16,
      percentage: 10 / 16,
      hasMore: false,
    });
  });

  it("keeps all-learning activity totals unavailable when a projection is missing", () => {
    const partialCollection: LearningCollectionResponse = {
      ...collection,
      items: [{ ...collection.items[0], projection: null }],
    };

    expect(buildAllLearningRollup(partialCollection)).toMatchObject({
      status: "available",
      courseCount: 1,
      completedCourseCount: 0,
      completedActivities: null,
      requiredActivities: null,
      percentage: null,
    });
  });

  it("renders the course scope with a source boundary and accessible scope control", () => {
    const html = renderToStaticMarkup(
      createElement(ProgressScopePanel, { learning, collection }),
    );

    expect(html).toContain("Learning progress");
    expect(html).toContain('role="group" aria-label="Progress scope"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("Your current course");
    expect(html).toContain(
      "<dd><strong>40%</strong><span>of required steps</span></dd>",
    );
    expect(html).not.toContain("</dd><span>");
    expect(html).toContain("Continue learning");
    expect(html).toContain(
      "Completed steps track participation, not an assessment of your skills.",
    );
    expect(html).not.toContain("XP");
    expect(html).not.toContain("leaderboard");
  });

  it.each([404, 405, 501])(
    "treats an explicitly unsupported collection route (%i) as unavailable",
    async (status) => {
      const result = await loadProgressData(
        progressApi(
          vi.fn(async () => {
            throw new ApiError(status, "collection route unavailable");
          }),
        ),
      );

      expect(result.learning).toEqual(learning);
      expect(result.learningCollection).toBeUndefined();
    },
  );

  it.each([401, 403, 500, 503])(
    "propagates collection auth/service failure (%i) for controlled recovery",
    async (status) => {
      const error = new ApiError(status, "collection request failed");

      await expect(
        loadProgressData(
          progressApi(
            vi.fn(async () => {
              throw error;
            }),
          ),
        ),
      ).rejects.toBe(error);
    },
  );

  it("propagates collection network failure instead of mislabeling it unavailable", async () => {
    const error = new TypeError("network unavailable");

    await expect(
      loadProgressData(
        progressApi(
          vi.fn(async () => {
            throw error;
          }),
        ),
      ),
    ).rejects.toBe(error);
  });

  it("propagates AbortError from the collection read while the runtime ignores it", async () => {
    const abortError = new Error("progress read stopped");
    abortError.name = "AbortError";

    await expect(
      loadProgressData(
        progressApi(
          vi.fn(async () => {
            throw abortError;
          }),
        ),
      ),
    ).rejects.toBe(abortError);
    expect(shouldIgnoreProgressLoadError(abortError)).toBe(true);
    expect(shouldIgnoreProgressLoadError(new Error("service failure"))).toBe(
      false,
    );
  });

  it("includes an offline collection snapshot in the route-level notice metadata", async () => {
    const offlineCollection = markOfflineRead(collection, 7_000);

    const result = await loadProgressData(
      progressApi(vi.fn(async () => offlineCollection)),
    );

    expect(result.offlineRead).toEqual({
      isOfflineCopy: true,
      savedAt: 7_000,
    });
  });

  it("keeps streak and achievement values unavailable until an explicit contract exists", () => {
    const html = renderToStaticMarkup(createElement(ProgressMotivationPanel));

    expect(html).toContain("Streak");
    expect(html).toContain("Achievements");
    expect(html).toContain("Unavailable");
    expect(html).toContain("Not available");
    expect(html).toContain("opt-in");
    expect(html).toContain("server-authorized");
    expect(html).toContain('aria-label="Streak value unavailable"');
    expect(html).not.toContain("aria-valuenow");
    expect(html).not.toContain("XP");
    expect(html).not.toContain("leaderboard");
  });
});
