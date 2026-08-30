import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createLearnerApi,
  type ActivityResponse,
  type ProgramDetailResponse,
} from "./learner-api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("learner API adapter", () => {
  it("uses injectable same-origin fetch for public catalog reads", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(input).toBe("/v1/programs?limit=50");
        expect(init?.credentials).toBe("include");
        return response({ items: [], next_cursor: null });
      },
    );
    const api = createLearnerApi(fetcher);

    await expect(api.listPrograms()).resolves.toEqual({
      items: [],
      next_cursor: null,
    });
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("rejects absolute and non-v1 paths before a request can escape the app", async () => {
    const fetcher = vi.fn();
    const api = createLearnerApi(fetcher);

    await expect(api.request("https://evil.example/v1/me")).rejects.toThrow(
      "same-origin /v1 path",
    );
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("sends an explicit free enrollment command with browser credentials and idempotency", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(input).toBe("/v1/enrollments/free");
        expect(init?.method).toBe("POST");
        expect(init?.credentials).toBe("include");
        expect(init?.cache).toBe("no-store");
        expect(Object.fromEntries(new Headers(init?.headers))).toEqual({
          accept: "application/json",
          "content-type": "application/json",
          "idempotency-key": "enroll-command-1",
        });
        expect(init?.body).toBe(
          JSON.stringify({ program_version_id: "version-1" }),
        );
        return response({
          enrollment_id: "enrollment-1",
          entitlement_id: "entitlement-1",
          provenance_id: "provenance-1",
          created: true,
          replayed: false,
        });
      },
    );
    const api = createLearnerApi(fetcher, {
      idempotencyKey: () => "enroll-command-1",
    });

    await expect(api.enrollFree("version-1")).resolves.toMatchObject({
      created: true,
    });
  });

  it("preserves server error status and code for honest UI states", async () => {
    const fetcher = vi.fn(async () =>
      response(
        { code: "authentication_required", title: "Sign in required" },
        401,
      ),
    );
    const api = createLearnerApi(fetcher);

    const failure = await api.me().catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      status: 401,
      code: "authentication_required",
      title: "Sign in required",
    });
  });

  it("uses the API's PUT draft and POST evidence verbs with server revisions", async () => {
    const ifMatches: string[] = [];
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        const headers = Object.fromEntries(new Headers(init?.headers));
        expect(init?.credentials).toBe("include");
        expect(headers["if-match"]).toBeDefined();
        ifMatches.push(headers["if-match"]);
        expect(headers["idempotency-key"]).toBe("command-1");
        if (path.endsWith("/draft")) {
          expect(init?.method).toBe("PUT");
          return response({
            id: "draft-1",
            activity_id: "activity-1",
            revision: 4,
            activity_revision: 7,
            status: "saved",
            payload: { response: "draft" },
            saved_at: "2026-08-30T00:00:00Z",
          });
        }
        expect(path).toBe("/v1/activities/activity-1/evidence");
        expect(init?.method).toBe("POST");
        return response({
          evidence_id: "evidence-1",
          submission_id: "submission-1",
          activity_id: "activity-1",
          activity_revision: 8,
          evidence_type: "reflection",
          submission_status: "pending",
        });
      },
    );
    const api = createLearnerApi(fetcher, {
      idempotencyKey: () => "command-1",
    });

    await expect(
      api.saveDraft("activity-1", { response: "draft" }, 0),
    ).resolves.toMatchObject({
      revision: 4,
    });
    await expect(
      api.submitEvidence("activity-1", "reflection", { response: "draft" }, 7),
    ).resolves.toMatchObject({
      submission_status: "pending",
      activity_revision: 8,
    });
    expect(ifMatches).toEqual(['"draft-revision-0"', '"activity-revision-7"']);
  });

  it("provides typed activity, learning, and certificate commands without client progress", async () => {
    const detail: ProgramDetailResponse = {
      id: "program-1",
      slug: "free-course",
      title: "Published course",
      program_version_id: "version-1",
      version_number: 1,
      published_at: "2026-08-30T00:00:00Z",
      modules: [],
    };
    const activity: ActivityResponse = {
      id: "activity-1",
      module_id: "module-1",
      program_version_id: "version-1",
      position: 1,
      kind: "reflection",
      title: "Published activity",
      prompt: null,
      state: "available",
      revision: 0,
      required: true,
      explanation: {
        activity_id: "activity-1",
        state: "available",
        required: true,
        reason: "server_resolved_activity_state",
        missing_activity_ids: [],
        missing_module_ids: [],
      },
      allowed_actions: [],
      enrollment_id: "enrollment-1",
      draft_revision: 0,
      draft_payload: null,
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/v1/programs/free-course") return response(detail);
      if (path === "/v1/activities/activity-1") return response(activity);
      if (path === "/v1/learning/program-1") {
        return response({
          program_id: "program-1",
          program_version_id: "version-1",
          program_slug: "free-course",
          program_title: "Published course",
          version_number: 1,
          enrollment_id: "enrollment-1",
          modules: [],
          projection: {
            scope_type: "program",
            scope_id: "program-1",
            program_version: "1",
            projection_version: "g1-v1",
            denominator: 5,
            completed_count: 0,
            percentage: 0,
            predicate: "required activities complete",
            missing_module_ids: [],
            activity_reasons: [],
          },
        });
      }
      return response({ id: "certificate-1", status: "issued" });
    });
    const api = createLearnerApi(fetcher);

    await expect(api.program("free-course")).resolves.toEqual(detail);
    await expect(api.activity("activity-1")).resolves.toEqual(activity);
    await expect(api.learning("program-1")).resolves.toMatchObject({
      program_id: "program-1",
      program_title: "Published course",
      projection: { percentage: 0, completed_count: 0, denominator: 5 },
    });
    await expect(api.certificate("certificate-1")).resolves.toEqual({
      id: "certificate-1",
      status: "issued",
    });
  });
});
