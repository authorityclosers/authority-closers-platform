import { describe, expect, it, vi } from "vitest";

import {
  loadLearnerHomeState,
  loadProgramLearningState,
} from "../components/learner-runtime";
import {
  ApiError,
  type LearnerApi,
  type MeResponse,
  type ProgramDetailResponse,
} from "./learner-api";

describe("learner home request sequencing", () => {
  it("starts identity, catalog, and onboarding reads together without a redundant context request", async () => {
    const calls: string[] = [];
    let resolveMe!: (value: MeResponse) => void;
    const me = new Promise<MeResponse>((resolve) => {
      resolveMe = resolve;
    });
    const context = vi.fn(() => {
      throw new Error("Home must not issue the redundant context request.");
    });
    const api = {
      me: vi.fn(() => {
        calls.push("me");
        return me;
      }),
      context,
      listPrograms: vi.fn(async () => {
        calls.push("programs");
        return { items: [], next_cursor: null };
      }),
      onboarding: vi.fn(async () => {
        calls.push("onboarding");
        return {
          person_id: "person-1",
          experience_context: null,
          learning_goal: null,
          practice_situation: null,
          weekly_minutes: null,
          status: "not_started" as const,
          current_step: 1,
          revision: 0,
          updated_at: "2026-09-01T00:00:00Z",
          next_action_href: "/onboarding",
          next_action_reason: "profile_required",
        };
      }),
    } as unknown as LearnerApi;

    const pending = loadLearnerHomeState(api);

    expect(calls).toEqual(["me", "programs", "onboarding"]);
    expect(context).not.toHaveBeenCalled();

    resolveMe({
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: null,
      membership_role: null,
      permissions: [],
    });

    const result = await pending;
    expect(result.onboarding.status).toBe("not_started");
    expect(result.learning).toBeUndefined();
  });

  it("starts program and identity reads together before requesting the authorized learning projection", async () => {
    const calls: string[] = [];
    let resolveProgram!: (value: ProgramDetailResponse) => void;
    let resolveMe!: (value: MeResponse) => void;
    const program = new Promise<ProgramDetailResponse>((resolve) => {
      resolveProgram = resolve;
    });
    const me = new Promise<MeResponse>((resolve) => {
      resolveMe = resolve;
    });
    const api = {
      program: vi.fn(() => {
        calls.push("program");
        return program;
      }),
      me: vi.fn(() => {
        calls.push("me");
        return me;
      }),
      learning: vi.fn(async () => {
        calls.push("learning");
        return {
          program_id: "program-1",
          program_version_id: "version-1",
          program_slug: "authority-closers-free-course",
          program_title: "Authority Closers Free Course",
          version_number: 1,
          enrollment_id: "enrollment-1",
          modules: [],
          projection: {
            scope_type: "program",
            scope_id: "program-1",
            program_version: "version-1",
            projection_version: "v1",
            denominator: 0,
            completed_count: 0,
            percentage: 0,
            predicate: "required_activities_complete",
            missing_module_ids: [],
            activity_reasons: [],
          },
        };
      }),
      context: vi.fn(),
      listPrograms: vi.fn(),
    } as unknown as LearnerApi;

    const pending = loadProgramLearningState(
      "authority-closers-free-course",
      api,
    );

    expect(calls).toEqual(["program", "me"]);

    resolveProgram({
      id: "program-1",
      slug: "authority-closers-free-course",
      title: "Authority Closers Free Course",
      program_version_id: "version-1",
      version_number: 1,
      published_at: "2026-09-01T00:00:00Z",
      modules: [],
    });
    resolveMe({
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: "tenant-1",
      membership_role: "learner",
      permissions: [],
    });

    const result = await pending;
    expect(calls).toEqual(["program", "me", "learning"]);
    expect(result.learning?.program_id).toBe("program-1");
    expect(api.context).not.toHaveBeenCalled();
    expect(api.listPrograms).not.toHaveBeenCalled();
  });

  it("prioritizes session recovery when a concurrent Home read also fails", async () => {
    const api = {
      me: vi.fn(async () => {
        await Promise.resolve();
        throw new ApiError(401, "Session expired");
      }),
      listPrograms: vi.fn(async () => {
        throw new ApiError(503, "Catalog unavailable");
      }),
      onboarding: vi.fn(async () => {
        throw new ApiError(500, "Onboarding unavailable");
      }),
    } as unknown as LearnerApi;

    await expect(loadLearnerHomeState(api)).rejects.toMatchObject({
      status: 401,
    });
  });

  it("prioritizes session recovery over a concurrent missing program", async () => {
    const api = {
      program: vi.fn(async () => {
        throw new ApiError(404, "Program not found");
      }),
      me: vi.fn(async () => {
        await Promise.resolve();
        throw new ApiError(401, "Session expired");
      }),
    } as unknown as LearnerApi;

    await expect(
      loadProgramLearningState("authority-closers-free-course", api),
    ).rejects.toMatchObject({ status: 401 });
  });
});
