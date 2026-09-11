import { describe, expect, it } from "vitest";

import type { LearningActivityResponse, LearningResponse } from "./learner-api";
import { firstActionableActivity } from "./next-learning-action";

function activity(
  id: string,
  overrides: Partial<LearningActivityResponse> = {},
): LearningActivityResponse {
  return {
    id,
    module_id: "module",
    program_version_id: "version",
    position: 1,
    kind: "REFLECTION",
    title: id,
    prompt: "Synthetic test prompt",
    state: "available",
    revision: 0,
    required: true,
    allowed_actions: ["save_draft"],
    explanation: {
      activity_id: id,
      state: "available",
      required: true,
      reason: "available",
      missing_activity_ids: [],
      missing_module_ids: [],
    },
    ...overrides,
  };
}

function learning(
  activities: LearningActivityResponse[],
  pointer?: string | null,
): LearningResponse {
  return {
    program_id: "program",
    program_version_id: "version",
    program_slug: "test-course",
    program_title: "Test course",
    version_number: 1,
    enrollment_id: "enrollment",
    modules: [{ id: "module", position: 1, title: "Module", activities }],
    projection: {
      scope_type: "course",
      scope_id: "program",
      program_version: "1",
      projection_version: "test-projection-v2",
      denominator: 2,
      completed_count: 0,
      percentage: 0,
      predicate: "required activities completed",
      missing_module_ids: [],
      activity_reasons: activities.map((item) => item.explanation),
      ...(pointer === undefined ? {} : { next_activity_id: pointer }),
    },
  };
}

describe("canonical next learning action", () => {
  it("uses the server pointer ahead of client array order without mutating input", () => {
    const response = learning([activity("first"), activity("next")], "next");
    const before = JSON.stringify(response);
    expect(firstActionableActivity(response)?.id).toBe("next");
    expect(JSON.stringify(response)).toBe(before);
  });

  it("honors an explicit no-action result even with action-enabled rows", () => {
    expect(
      firstActionableActivity(learning([activity("first")], null)),
    ).toBeUndefined();
  });

  it.each(["locked", "awaiting_review", "completed"])(
    "never resumes a pointed %s row even with stale allowed actions",
    (state) => {
      expect(
        firstActionableActivity(
          learning(
            [activity("blocked", { state }), activity("eligible")],
            "blocked",
          ),
        )?.id,
      ).toBe("eligible");
    },
  );

  it.each(["blocked", "missing"])(
    "rejects a %s pointer and skips optional activities and optional modules",
    (pointer) => {
      const optional = activity("optional", { required: false });
      optional.explanation.required = false;
      const optionalModule = activity("optional-module");
      optionalModule.explanation.required = false;
      const response = learning(
        [
          activity("blocked", { allowed_actions: [] }),
          optional,
          optionalModule,
          activity("required-next"),
        ],
        pointer,
      );
      expect(firstActionableActivity(response)?.id).toBe("required-next");
    },
  );

  it("does not follow a stale pointer into an optional module", () => {
    const optionalModule = activity("optional-module");
    optionalModule.explanation.required = false;
    expect(
      firstActionableActivity(
        learning([optionalModule, activity("required")], "optional-module"),
      )?.id,
    ).toBe("required");
  });

  it("returns no action when a modern fallback has only optional work", () => {
    const optional = activity("optional");
    optional.explanation.required = false;
    expect(
      firstActionableActivity(learning([optional], "missing")),
    ).toBeUndefined();
  });

  it("keeps the state-and-action-checked fallback for older API responses", () => {
    const optional = activity("optional");
    optional.explanation.required = false;
    expect(
      firstActionableActivity(
        learning([activity("disabled", { allowed_actions: [] }), optional]),
      )?.id,
    ).toBe("optional");
  });
});
