import { describe, expect, it } from "vitest";

import { firstActionableActivity } from "../components/dashboard-runtime";
import type {
  ActivityAllowedAction,
  LearningActivityResponse,
  LearningResponse,
} from "./learner-api";

function activity(
  id: string,
  state: string,
  allowedActions: ActivityAllowedAction[],
  moduleId: string,
  position: number,
): LearningActivityResponse {
  return {
    id,
    module_id: moduleId,
    program_version_id: "version-1",
    position,
    kind: "REFLECTION",
    title: id,
    prompt: null,
    state,
    revision: 1,
    required: true,
    explanation: {
      activity_id: id,
      state,
      required: true,
      reason: "Synthetic acceptance fixture.",
      missing_activity_ids: [],
      missing_module_ids: [],
    },
    allowed_actions: allowedActions,
  };
}

function learning(modules: LearningResponse["modules"]): LearningResponse {
  return {
    program_id: "program-1",
    program_version_id: "version-1",
    program_slug: "synthetic-free-course",
    program_title: "Synthetic free course",
    version_number: 1,
    enrollment_id: "enrollment-1",
    modules,
    projection: {
      scope_type: "course",
      scope_id: "program-1",
      program_version: "1",
      projection_version: "1",
      denominator: 2,
      completed_count: 0,
      percentage: 0,
      predicate: "required activities completed",
      missing_module_ids: [],
      activity_reasons: [],
    },
  };
}

describe("free-course learning resume acceptance", () => {
  it("resumes the first server-authorized activity across the published module order", () => {
    const result = firstActionableActivity(
      learning([
        {
          id: "module-1",
          position: 1,
          title: "First module",
          activities: [activity("locked-first", "locked", [], "module-1", 1)],
        },
        {
          id: "module-2",
          position: 2,
          title: "Second module",
          activities: [
            activity(
              "resume-here",
              "in_progress",
              ["save_draft"],
              "module-2",
              1,
            ),
          ],
        },
      ]),
    );

    expect(result?.id).toBe("resume-here");
    expect(result?.allowed_actions).toEqual(["save_draft"]);
  });

  it("does not invent a first lesson when the server exposes no allowed action", () => {
    const result = firstActionableActivity(
      learning([
        {
          id: "module-1",
          position: 1,
          title: "First module",
          activities: [
            activity(
              "available-without-action",
              "available",
              [],
              "module-1",
              1,
            ),
            activity("completed", "completed", [], "module-1", 2),
          ],
        },
      ]),
    );

    expect(result).toBeUndefined();
  });

  it("returns no continuation for an empty or entirely locked course path", () => {
    expect(
      firstActionableActivity(
        learning([
          {
            id: "empty-module",
            position: 1,
            title: "Empty module",
            activities: [],
          },
          {
            id: "locked-module",
            position: 2,
            title: "Locked module",
            activities: [activity("locked", "locked", [], "locked-module", 1)],
          },
        ]),
      ),
    ).toBeUndefined();
  });
});
