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

  it("retains an enrollment key after an unknown outcome and rotates it after success", async () => {
    const observedKeys: string[] = [];
    let requestCount = 0;
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        requestCount += 1;
        if (requestCount === 1) throw new TypeError("connection lost");
        return response({ created: requestCount === 2, replayed: false });
      },
    );
    const makeKey = vi
      .fn<() => string>()
      .mockReturnValueOnce("enrollment-operation-1")
      .mockReturnValueOnce("enrollment-operation-2");
    const api = createLearnerApi(fetcher, { idempotencyKey: makeKey });

    await expect(api.enrollFree("version-retry")).rejects.toThrow(
      "connection lost",
    );
    await expect(api.enrollFree("version-retry")).resolves.toMatchObject({
      created: true,
    });
    await expect(api.enrollFree("version-retry")).resolves.toMatchObject({
      created: false,
    });

    expect(observedKeys).toEqual([
      "enrollment-operation-1",
      "enrollment-operation-1",
      "enrollment-operation-2",
    ]);
    expect(makeKey).toHaveBeenCalledTimes(2);
  });

  it("retains one key for retries of the same logical draft", async () => {
    const observedKeys: string[] = [];
    const fetcher = vi
      .fn()
      .mockImplementationOnce(async (_input, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        throw new TypeError("offline");
      })
      .mockImplementationOnce(async (_input, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        return response({ revision: 2, activity_revision: 4 });
      });
    const makeKey = vi.fn(() => `draft-operation-${observedKeys.length + 1}`);
    const api = createLearnerApi(fetcher, { idempotencyKey: makeKey });

    await expect(
      api.saveDraft("activity-retry", { response: "Keep this" }, 1),
    ).rejects.toThrow("offline");
    await expect(
      api.saveDraft("activity-retry", { response: "Keep this" }, 1),
    ).resolves.toMatchObject({ revision: 2 });

    expect(observedKeys).toEqual(["draft-operation-1", "draft-operation-1"]);
    expect(makeKey).toHaveBeenCalledOnce();
  });

  it("retains one key for retries of the same logical evidence submission", async () => {
    const observedKeys: string[] = [];
    const fetcher = vi
      .fn()
      .mockImplementationOnce(async (_input, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        return response({ code: "upstream_timeout" }, 503);
      })
      .mockImplementationOnce(async (_input, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        return response({ activity_revision: 9, submission_status: "pending" });
      });
    const makeKey = vi.fn(
      () => `evidence-operation-${observedKeys.length + 1}`,
    );
    const api = createLearnerApi(fetcher, { idempotencyKey: makeKey });

    await expect(
      api.submitEvidence(
        "activity-evidence",
        "reflection",
        { response: "One submission" },
        8,
      ),
    ).rejects.toMatchObject({ status: 503 });
    await expect(
      api.submitEvidence(
        "activity-evidence",
        "reflection",
        { response: "One submission" },
        8,
      ),
    ).resolves.toMatchObject({ activity_revision: 9 });

    expect(observedKeys).toEqual([
      "evidence-operation-1",
      "evidence-operation-1",
    ]);
    expect(makeKey).toHaveBeenCalledOnce();
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

  it("keeps password challenges in JSON bodies and consent authority off the client", async () => {
    const requests: Array<{ path: string; body: unknown }> = [];
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        requests.push({
          path: String(input),
          body:
            typeof init?.body === "string"
              ? (JSON.parse(init.body) as unknown)
              : null,
        });
        if (String(input).endsWith("/register")) {
          return response({ status: "verification_required" }, 202);
        }
        if (String(input).endsWith("/verify")) {
          return response({
            authenticated: true,
            person_id: "person-1",
            email: "learner@example.com",
            display_name: "Learner",
          });
        }
        return response({ reset: true });
      },
    );
    const api = createLearnerApi(fetcher, {
      idempotencyKey: () => "identity-command-1",
    });

    await api.registerPassword({
      firstName: "Learner",
      email: "learner@example.com",
      whatsappNumber: "+12025550123",
      password: "twelve-characters-and-more",
      consent: true,
    });
    await api.verifyPasswordEmail("v".repeat(43));
    await api.resetPassword("r".repeat(43), "another-long-password");

    expect(requests).toEqual([
      {
        path: "/v1/auth/password/register",
        body: {
          first_name: "Learner",
          email: "learner@example.com",
          whatsapp_number: "+12025550123",
          password: "twelve-characters-and-more",
          consent: true,
        },
      },
      {
        path: "/v1/auth/password/verify",
        body: { token: "v".repeat(43) },
      },
      {
        path: "/v1/auth/password/reset",
        body: {
          token: "r".repeat(43),
          new_password: "another-long-password",
        },
      },
    ]);
    expect(requests.every(({ path }) => !path.includes("token="))).toBe(true);
    expect(requests[0]?.body).not.toHaveProperty("consent_version");
  });

  it("requests a verification resend without exposing account existence", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(input).toBe("/v1/auth/password/resend-verification");
        expect(JSON.parse(String(init?.body))).toEqual({
          email: "learner@example.com",
        });
        return response({ accepted: true });
      },
    );

    await expect(
      createLearnerApi(fetcher).resendPasswordVerification(
        "learner@example.com",
      ),
    ).resolves.toEqual({ accepted: true });
  });

  it("replaces onboarding with an optimistic revision and no client-side recommendation", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(input).toBe("/v1/onboarding");
        expect(init?.method).toBe("PUT");
        expect(new Headers(init?.headers).get("if-match")).toBe(
          '"onboarding-revision-3"',
        );
        expect(JSON.parse(String(init?.body))).toEqual({
          experience_context: "sales",
          learning_goal: "Ask a clearer next-step question",
          practice_situation: null,
          weekly_minutes: 30,
          status: "completed",
          current_step: 3,
        });
        return response({
          person_id: "person-1",
          experience_context: "sales",
          learning_goal: "Ask a clearer next-step question",
          practice_situation: null,
          weekly_minutes: 30,
          status: "completed",
          current_step: 3,
          revision: 4,
          updated_at: "2026-08-31T00:00:00Z",
          next_action_href: "/",
          next_action_reason: "Server-owned explanation",
        });
      },
    );
    const api = createLearnerApi(fetcher, {
      idempotencyKey: () => "onboarding-command-1",
    });

    await expect(
      api.saveOnboarding(
        {
          experienceContext: "sales",
          learningGoal: "Ask a clearer next-step question",
          practiceSituation: null,
          weeklyMinutes: 30,
          status: "completed",
          currentStep: 3,
        },
        3,
      ),
    ).resolves.toMatchObject({
      status: "completed",
      revision: 4,
      next_action_reason: "Server-owned explanation",
    });
  });

  it("retains one onboarding key after a lost response and rotates it after success", async () => {
    const observedKeys: string[] = [];
    const fetcher = vi
      .fn()
      .mockImplementationOnce(async (_input, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        throw new TypeError("response lost after commit");
      })
      .mockImplementationOnce(async (_input, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        return response({ revision: 4, status: "completed" });
      })
      .mockImplementationOnce(async (_input, init?: RequestInit) => {
        observedKeys.push(
          new Headers(init?.headers).get("idempotency-key") ?? "missing",
        );
        return response({ revision: 5, status: "completed" });
      });
    const makeKey = vi
      .fn<() => string>()
      .mockReturnValueOnce("onboarding-operation-1")
      .mockReturnValueOnce("onboarding-operation-2");
    const api = createLearnerApi(fetcher, { idempotencyKey: makeKey });
    const input = {
      experienceContext: "sales",
      learningGoal: "Ask a clearer next-step question",
      practiceSituation: null,
      weeklyMinutes: 30,
      status: "completed" as const,
      currentStep: 3,
    };

    await expect(api.saveOnboarding(input, 3)).rejects.toThrow(
      "response lost after commit",
    );
    await expect(api.saveOnboarding(input, 3)).resolves.toMatchObject({
      revision: 4,
    });
    await expect(api.saveOnboarding(input, 4)).resolves.toMatchObject({
      revision: 5,
    });

    expect(observedKeys).toEqual([
      "onboarding-operation-1",
      "onboarding-operation-1",
      "onboarding-operation-2",
    ]);
    expect(makeKey).toHaveBeenCalledTimes(2);
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
