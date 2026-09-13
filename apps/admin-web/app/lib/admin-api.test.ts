import { afterEach, describe, expect, it, vi } from "vitest";

import {
  appendCorrection,
  appendStudioActivity,
  appendStudioModule,
  createStudioRevision,
  grantEnrollment,
  loadAdminSession,
  loadStudioProgram,
  loadStudioPrograms,
  loadStudioReadiness,
  publishProgramVersion,
  reconcileRecovery,
  retryJob,
  updateStudioActivity,
  updateStudioModule,
  type StudioActivityKind,
  type StudioDraftMutationResponse,
} from "./admin-api";

const personId = "11111111-1111-4111-8111-111111111111";
const sessionId = "22222222-2222-4222-8222-222222222222";
const tenantId = "33333333-3333-4333-8333-333333333333";
const versionId = "44444444-4444-4444-8444-444444444444";
const submissionId = "55555555-5555-4555-8555-555555555555";
const jobId = "66666666-6666-4666-8666-666666666666";
const outboxId = "77777777-7777-4777-8777-777777777777";

const publishResponse = {
  id: versionId,
  program_id: "88888888-8888-4888-8888-888888888888",
  version_number: 2,
  status: "published",
  supersedes_version_id: null,
  published_at: "2026-08-30T00:00:00Z",
  replayed: false,
};
const versionEtag = '"program-version-' + "a".repeat(64) + '"';
const publishCommandKey = "publish-command-1";
const programId = "88888888-8888-4888-8888-888888888888";
const moduleId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const activityId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const studioReadinessResponse = {
  tenant_id: tenantId,
  draft_backlog_count: 1,
  as_of: "2026-08-31T00:00:00Z",
  oldest_draft_created_at: "2026-08-30T00:00:00Z",
  oldest_draft_age_seconds: 86_400,
  drafts: [
    {
      program_id: programId,
      program_title: "Authority Closers Academy",
      program_version_id: versionId,
      version_number: 2,
      created_at: "2026-08-30T00:00:00Z",
      age_seconds: 86_400,
      etag: versionEtag,
      ready: true,
      blockers: [],
    },
  ],
  truncated: false,
  arrival_rate: {
    status: "unavailable",
    value: null,
    reason: "No canonical rate.",
  },
  service_rate: {
    status: "unavailable",
    value: null,
    reason: "No canonical rate.",
  },
  planned_capacity: {
    status: "unavailable",
    value: null,
    reason: "No capacity plan.",
  },
} as const;
const studioProgramsResponse = {
  tenant_id: tenantId,
  programs: [
    {
      id: programId,
      slug: "authority-closers-academy",
      title: "Authority Closers Academy",
      scope: "tenant",
      access: "selected_tenant",
      version_count: 1,
      draft_count: 1,
      current_published_version_id: null,
      latest_version: {
        id: versionId,
        version_number: 2,
        status: "draft",
        created_at: "2026-08-30T00:00:00Z",
        published_at: null,
      },
    },
  ],
  truncated: false,
} as const;
const studioProgramResponse = {
  tenant_id: tenantId,
  id: programId,
  slug: "authority-closers-academy",
  title: "Authority Closers Academy",
  scope: "tenant",
  access: "selected_tenant",
  versions: [
    {
      ...studioProgramsResponse.programs[0].latest_version,
      supersedes_version_id: null,
      content_source_ref: "controlled-doc",
      content_reviewed_by: "reviewer@example.test",
      content_reviewed_at: "2026-08-30T00:00:00Z",
      release_id: "a".repeat(40),
      content_seed_kind: "reviewed",
      content_digest: "b".repeat(64),
      etag: versionEtag,
      readiness: "ready",
      blockers: [],
      modules: [],
    },
  ],
  versions_truncated: false,
} as const;

function draftMutationResponse(
  resourceId = moduleId,
): StudioDraftMutationResponse {
  return {
    program: {
      ...studioProgramResponse,
      versions: [
        {
          ...studioProgramResponse.versions[0],
          blockers: [],
          modules: [
            {
              id: moduleId,
              position: 1,
              title: "Start with the customer",
              prerequisite_module_ids: [],
              activities: [
                {
                  id: activityId,
                  position: 1,
                  kind: "REFLECTION",
                  title: "The next question",
                  prompt: "What would you ask next?",
                  is_required: true,
                },
              ],
            },
          ],
        },
      ],
    },
    resource_id: resourceId,
    replayed: false,
  };
}

const draftCommand = {
  programVersionId: versionId,
  ifMatch: versionEtag,
  idempotencyKey: "studio-draft-command-1",
  origin: "http://admin.localhost:3101",
};

function revisionResponse(): StudioDraftMutationResponse {
  const result = draftMutationResponse();
  result.resource_id = moduleId;
  result.program.versions[0].id = moduleId;
  result.program.versions[0].supersedes_version_id = versionId;
  return result;
}

describe("Studio course revisions", () => {
  it("sends a bounded same-origin command with exact precondition and no inferred copy flags", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(revisionResponse()));
    const signal = new AbortController().signal;
    const result = await createStudioRevision({
      ...draftCommand,
      programId,
      tenantId,
      fetcher,
      signal,
    });
    expect(result.resource_id).toBe(moduleId);
    const [path, request] = fetcher.mock.calls[0];
    expect(path).toBe(
      `/v1/admin/studio/program-versions/${versionId}/revision`,
    );
    expect(request).toMatchObject({
      method: "POST",
      body: "{}",
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
    const headers = new Headers(request?.headers);
    expect(headers.get("if-match")).toBe(versionEtag);
    expect(headers.get("idempotency-key")).toBe(draftCommand.idempotencyKey);
  });
  it.each(["tenant", "program", "source", "resource", "scope", "status"])(
    "rejects a revision response with a wrong %s",
    async (mismatch) => {
      const result = revisionResponse();
      if (mismatch === "tenant") result.program.tenant_id = personId;
      if (mismatch === "program") result.program.id = personId;
      if (mismatch === "source")
        result.program.versions[0].supersedes_version_id = personId;
      if (mismatch === "resource") result.resource_id = personId;
      if (mismatch === "scope") result.program.access = "global_read_only";
      if (mismatch === "status")
        result.program.versions[0].status = "published";
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(result));
      await expect(
        createStudioRevision({ ...draftCommand, programId, tenantId, fetcher }),
      ).rejects.toThrow();
    },
  );
  it("accepts a valid replay after the original revision has been published", async () => {
    const result = revisionResponse();
    result.replayed = true;
    result.program.versions[0].status = "published";
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(result));
    await expect(
      createStudioRevision({ ...draftCommand, programId, tenantId, fetcher }),
    ).resolves.toMatchObject({ replayed: true });
  });
  it("validates identifiers, precondition, and key before any network request", () => {
    const fetcher = vi.fn<typeof fetch>();
    for (const invalid of [
      { programId: "other" },
      { tenantId: "other" },
      { programVersionId: "other" },
      { ifMatch: "*" },
      { idempotencyKey: "" },
      { idempotencyKey: "a\nb" },
    ]) {
      expect(() =>
        createStudioRevision({
          ...draftCommand,
          programId,
          tenantId,
          fetcher,
          ...invalid,
        }),
      ).toThrow();
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
});

const draftAdapters = [
  {
    name: "append module",
    suffix: "modules",
    method: "POST",
    resourceId: moduleId,
    payload: { title: "Start with the customer" },
    invoke: (fetcher: typeof fetch, signal?: AbortSignal) =>
      appendStudioModule({
        ...draftCommand,
        title: "Start with the customer",
        fetcher,
        signal,
      }),
  },
  {
    name: "update module",
    suffix: `modules/${moduleId}`,
    method: "PATCH",
    resourceId: moduleId,
    payload: { title: "Start with the customer" },
    invoke: (fetcher: typeof fetch, signal?: AbortSignal) =>
      updateStudioModule({
        ...draftCommand,
        moduleId,
        title: "Start with the customer",
        fetcher,
        signal,
      }),
  },
  {
    name: "append activity",
    suffix: `modules/${moduleId}/activities`,
    method: "POST",
    resourceId: activityId,
    payload: {
      kind: "REFLECTION",
      title: "The next question",
      prompt: "What would you ask next?",
      is_required: true,
    },
    invoke: (fetcher: typeof fetch, signal?: AbortSignal) =>
      appendStudioActivity({
        ...draftCommand,
        moduleId,
        kind: "REFLECTION",
        title: "The next question",
        prompt: "What would you ask next?",
        isRequired: true,
        fetcher,
        signal,
      }),
  },
  {
    name: "update activity",
    suffix: `activities/${activityId}`,
    method: "PATCH",
    resourceId: activityId,
    payload: { title: "The next question", prompt: null },
    invoke: (fetcher: typeof fetch, signal?: AbortSignal) =>
      updateStudioActivity({
        ...draftCommand,
        activityId,
        title: "The next question",
        prompt: null,
        fetcher,
        signal,
      }),
  },
] as const;
const correctionResponse = {
  correction_id: "99999999-9999-4999-8999-999999999999",
  submission_id: submissionId,
  decision: "approved",
  correction_sequence: 1,
  supersedes_correction_id: null,
};
const grantResponse = {
  enrollment_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  entitlement_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  provenance_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  command_idempotency_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  created: true,
  replayed: false,
};
const retryResponse = {
  job_id: jobId,
  status: "queued",
  attempt_count: 1,
  recovery_generation: 0,
  held: false,
  replayed: false,
};
const reconcileResponse = {
  job_ids: [jobId],
  outbox_event_ids: [outboxId],
  recovery_generation: 1,
  recovery_status: "reconciled",
  replayed: false,
};

const me = {
  person_id: personId,
  email: "admin@authorityclosers.com",
  display_name: "AC Admin",
  email_verified_at: "2026-08-30T00:00:00Z",
  selected_tenant_id: tenantId,
  membership_role: "admin",
  permissions: ["admin_surface", "catalog_publish", "learning_correct"],
};

const context = {
  person_id: personId,
  session_id: sessionId,
  tenant_id: tenantId,
  membership_role: "admin",
  permissions: ["admin_surface", "catalog_publish", "learning_correct"],
};

const studioAccess = {
  person_id: personId,
  session_id: sessionId,
  tenant_id: tenantId,
  studio_capabilities: [],
};

type MutationAdapter = (fetcher: typeof fetch) => Promise<unknown>;

const mutationAdapters: ReadonlyArray<readonly [string, MutationAdapter]> = [
  [
    "publish",
    (fetcher) =>
      publishProgramVersion({
        programVersionId: versionId,
        reason: "approved release",
        ifMatch: versionEtag,
        idempotencyKey: publishCommandKey,
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
  ],
  [
    "correction",
    (fetcher) =>
      appendCorrection({
        submissionId,
        decision: "approved",
        reason: "reviewed evidence",
        ifMatch: '"submission-revision-4"',
        idempotencyKey: "correction-empty-response",
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
  ],
  [
    "enrollment grant",
    (fetcher) =>
      grantEnrollment({
        personId,
        programVersionId: versionId,
        reason: "support grant",
        idempotencyKey: "grant-empty-response",
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
  ],
  [
    "job retry",
    (fetcher) =>
      retryJob({
        jobId,
        reason: "reviewed retry",
        idempotencyKey: "retry-empty-response",
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
  ],
  [
    "recovery reconcile",
    (fetcher) =>
      reconcileRecovery({
        jobIds: [jobId],
        outboxEventIds: [outboxId],
        reason: "reviewed reconciliation",
        idempotencyKey: "reconcile-empty-response",
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
  ],
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("version-pinned Studio authoring", () => {
  it.each(draftAdapters)(
    "$name sends only its canonical fields, caller preconditions, and same-origin session",
    async ({ invoke, method, suffix, payload, resourceId }) => {
      const response = draftMutationResponse(resourceId);
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(response));
      const controller = new AbortController();
      await expect(invoke(fetcher, controller.signal)).resolves.toEqual(
        response,
      );
      expect(fetcher).toHaveBeenCalledOnce();
      const [url, init] = fetcher.mock.calls[0];
      expect(url).toBe(
        `/v1/admin/studio/program-versions/${versionId}/${suffix}`,
      );
      expect(init).toMatchObject({
        method,
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual({
        accept: "application/json",
        "content-type": "application/json",
        origin: draftCommand.origin,
        "if-match": versionEtag,
        "idempotency-key": draftCommand.idempotencyKey,
      });
      expect(JSON.parse(String(init?.body))).toEqual(payload);
    },
  );

  it.each(draftAdapters)(
    "$name keeps the exact caller intent on an unknown-outcome retry without retrying automatically",
    async ({ invoke, resourceId }) => {
      const lostResponse = new TypeError("Network interrupted");
      const response = draftMutationResponse(resourceId);
      response.replayed = true;
      response.program.versions[0].etag =
        '"program-version-' + "c".repeat(64) + '"';
      const fetcher = vi
        .fn<typeof fetch>()
        .mockRejectedValueOnce(lostResponse)
        .mockResolvedValueOnce(Response.json(response));
      await expect(invoke(fetcher)).rejects.toBe(lostResponse);
      expect(fetcher).toHaveBeenCalledOnce();
      await expect(invoke(fetcher)).resolves.toEqual(response);
      const [[firstUrl, first], [secondUrl, second]] = fetcher.mock.calls;
      expect(secondUrl).toBe(firstUrl);
      expect(second?.body).toBe(first?.body);
      expect(Object.fromEntries(new Headers(second?.headers))).toEqual(
        Object.fromEntries(new Headers(first?.headers)),
      );
    },
  );

  it("snapshots submitted text without trimming or mutating the caller's editable fields", async () => {
    let resolveResponse!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockReturnValue(
      new Promise((resolve) => {
        resolveResponse = resolve;
      }),
    );
    const input = {
      ...draftCommand,
      moduleId,
      title: "  Original title  ",
      fetcher,
    };
    const pending = updateStudioModule(input);
    input.title = "New unsaved typing";
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      title: "  Original title  ",
    });
    resolveResponse(Response.json(draftMutationResponse()));
    await pending;
    expect(input.title).toBe("New unsaved typing");
  });

  it("accepts the current immutable program on a replay, not only the original draft snapshot", async () => {
    const response = draftMutationResponse();
    response.replayed = true;
    Object.assign(response.program.versions[0], {
      status: "published",
      published_at: "2026-09-08T05:00:00Z",
      etag: null,
      readiness: "immutable",
    });
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(response));
    await expect(draftAdapters[1].invoke(fetcher)).resolves.toEqual(response);
  });

  it.each(draftAdapters)(
    "$name rejects empty or malformed success instead of inventing saved state",
    async ({ invoke }) => {
      for (const response of [
        new Response(null, { status: 204 }),
        new Response("<html>Login</html>", { status: 200 }),
        Response.json({ program: studioProgramResponse }),
        Response.json({
          ...draftMutationResponse(),
          unexpected_authority: "admin",
        }),
      ]) {
        const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response);
        await expect(invoke(fetcher)).rejects.toThrow();
        expect(fetcher).toHaveBeenCalledOnce();
      }
    },
  );

  it.each([
    [401, "authentication_required"],
    [403, "admin_authorization_denied"],
    [404, "resource_not_found"],
    [409, "studio_draft_conflict"],
    [412, "studio_draft_precondition_failed"],
    [422, "studio_draft_invalid"],
    [428, "admin_if_match_required"],
    [428, "admin_idempotency_key_required"],
    [500, "internal_error"],
  ])(
    "preserves HTTP %i / %s for explicit editor recovery",
    async (status, code) => {
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
        Response.json(
          {
            title: "Draft not saved",
            detail: "Refresh the current draft before continuing.",
            code,
            request_id: "synthetic-request-1",
          },
          { status },
        ),
      );
      await expect(draftAdapters[0].invoke(fetcher)).rejects.toMatchObject({
        name: "AdminApiProblem",
        status,
        code,
        requestId: "synthetic-request-1",
      });
      expect(fetcher).toHaveBeenCalledOnce();
    },
  );

  it("propagates cancellation without claiming the server rolled back", async () => {
    const controller = new AbortController();
    const cancellation = new DOMException("Aborted", "AbortError");
    const fetcher = vi.fn<typeof fetch>().mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(cancellation));
        }),
    );
    const pending = draftAdapters[2].invoke(fetcher, controller.signal);
    controller.abort();
    await expect(pending).rejects.toBe(cancellation);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it.each([
    [
      "other version",
      (value: StudioDraftMutationResponse) => {
        value.program.versions[0].id = sessionId;
      },
    ],
    [
      "other resource",
      (value: StudioDraftMutationResponse) => {
        value.resource_id = sessionId;
      },
    ],
    [
      "global program",
      (value: StudioDraftMutationResponse) => {
        value.program.scope = "global";
      },
    ],
    [
      "read-only access",
      (value: StudioDraftMutationResponse) => {
        value.program.access = "global_read_only";
      },
    ],
    [
      "missing module",
      (value: StudioDraftMutationResponse) => {
        value.program.versions[0].modules = [];
      },
    ],
    [
      "duplicate module",
      (value: StudioDraftMutationResponse) => {
        value.program.versions[0].modules.push(
          value.program.versions[0].modules[0],
        );
      },
    ],
    [
      "duplicate version",
      (value: StudioDraftMutationResponse) => {
        value.program.versions.push(value.program.versions[0]);
      },
    ],
  ] as const)("rejects a saved response for %s", async (_name, change) => {
    const response = draftMutationResponse();
    change(response);
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(response));
    await expect(draftAdapters[1].invoke(fetcher)).rejects.toThrow();
  });

  it("rejects an appended activity attached to a different module", async () => {
    const response = draftMutationResponse(activityId);
    response.program.versions[0].modules[0].id = sessionId;
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(response));
    await expect(draftAdapters[2].invoke(fetcher)).rejects.toThrow();
  });

  it("rejects duplicate activity identities in a successful response", async () => {
    const response = draftMutationResponse(activityId);
    const activities = response.program.versions[0].modules[0].activities;
    activities.push(activities[0]);
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(response));
    await expect(draftAdapters[3].invoke(fetcher)).rejects.toThrow();
  });

  it.each([
    { programVersionId: "//other.example/v1" },
    { programVersionId: "../publish" },
    { moduleId: "../activities" },
    { ifMatch: "*" },
    { ifMatch: "" },
    { ifMatch: 'W/"program-version-' + "a".repeat(64) + '"' },
    { idempotencyKey: "" },
    { idempotencyKey: "x".repeat(129) },
    { idempotencyKey: "changed\nheader" },
    { idempotencyKey: "\u007f" },
    { idempotencyKey: " trailing " },
    { title: " \n " },
    { title: "x".repeat(201) },
  ])(
    "rejects invalid module input before making any request: %j",
    (invalid) => {
      const fetcher = vi.fn<typeof fetch>();
      expect(() =>
        updateStudioModule({
          ...draftCommand,
          moduleId,
          title: "Module",
          ...invalid,
          fetcher,
        }),
      ).toThrow();
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it.each([
    { activityId: "../modules" },
    { title: "x".repeat(241) },
    { prompt: "" },
    { prompt: "  \n " },
    { prompt: "x".repeat(2001) },
  ])(
    "rejects invalid activity input before making any request: %j",
    (invalid) => {
      const fetcher = vi.fn<typeof fetch>();
      expect(() =>
        updateStudioActivity({
          ...draftCommand,
          activityId,
          title: "Activity",
          prompt: null,
          ...invalid,
          fetcher,
        }),
      ).toThrow();
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it.each([
    "VIDEO",
    "REFLECTION",
    "IMPLEMENTATION_CHALLENGE",
    "REVIEW",
    "IMPROVE",
  ] as const)(
    "sends authored %s without changing the required choice",
    async (kind) => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(draftMutationResponse(activityId)));
      await appendStudioActivity({
        ...draftCommand,
        moduleId,
        kind,
        title: "Activity",
        prompt: null,
        isRequired: false,
        fetcher,
      });
      expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({
        kind,
        is_required: false,
      });
    },
  );

  it("fails closed for an unsupported runtime activity kind", () => {
    const fetcher = vi.fn<typeof fetch>();
    expect(() =>
      appendStudioActivity({
        ...draftCommand,
        moduleId,
        kind: "AUTONOMOUS_SCORING" as StudioActivityKind,
        title: "Activity",
        prompt: null,
        isRequired: true,
        fetcher,
      }),
    ).toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("accepts title limits measured as Unicode characters and normalizes only UUID paths", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(draftMutationResponse()));
    await updateStudioModule({
      ...draftCommand,
      moduleId: moduleId.toUpperCase(),
      title: "🌱".repeat(200),
      fetcher,
    });
    expect(fetcher.mock.calls[0][0]).toBe(
      `/v1/admin/studio/program-versions/${versionId}/modules/${moduleId}`,
    );
  });
});

describe("same-origin admin API composition", () => {
  it("starts independent identity reads together and waits for all matching projections", async () => {
    const waiting = new Map<string, (response: Response) => void>();
    const fetcher = vi.fn<typeof fetch>(
      (path) =>
        new Promise<Response>((resolve) => {
          waiting.set(String(path), resolve);
        }),
    );
    let admitted = false;
    const result = loadAdminSession(fetcher).then((session) => {
      admitted = true;
      return session;
    });
    expect([...waiting.keys()]).toEqual([
      "/v1/me",
      "/v1/context",
      "/v1/me/studio-access",
    ]);
    waiting.get("/v1/context")!(Response.json(context));
    waiting.get("/v1/me/studio-access")!(Response.json(studioAccess));
    await Promise.resolve();
    expect(admitted).toBe(false);
    waiting.get("/v1/me")!(Response.json(me));
    await expect(result).resolves.toMatchObject({
      personId,
      tenantId,
      sessionId,
    });
  });
  it.each([401, 403])(
    "marks definitive HTTP %s session rejection as denied",
    async (status) => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response("", { status }));
      await expect(loadAdminSession(fetcher)).rejects.toMatchObject({
        code: "admin_session_denied",
      });
    },
  );
  it("preserves server and network failures as retryable errors, not signed-out evidence", async () => {
    const server = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response("", { status: 503 }));
    await expect(loadAdminSession(server)).rejects.toMatchObject({
      status: 503,
    });
    const offline = new TypeError("Network unavailable");
    const network = vi.fn<typeof fetch>().mockRejectedValue(offline);
    await expect(loadAdminSession(network)).rejects.toBe(offline);
  });
  it("admits an assigned learner through the separate canonical Studio projection", async () => {
    const capability = {
      permission: "catalog_read",
      scope_kind: "program",
      tenant_id: tenantId,
      program_id: versionId,
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json({ ...me, membership_role: "learner", permissions: [] }),
      )
      .mockResolvedValueOnce(
        Response.json({
          ...context,
          membership_role: "learner",
          permissions: [],
        }),
      )
      .mockResolvedValueOnce(
        Response.json({ ...studioAccess, studio_capabilities: [capability] }),
      );
    await expect(loadAdminSession(fetcher)).resolves.toMatchObject({
      membershipRole: "learner",
      permissions: [],
      studioCapabilities: [capability],
    });
  });
  it("requires both canonical product identity and selected admin context", async () => {
    const controller = new AbortController();
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(me))
      .mockResolvedValueOnce(Response.json(context))
      .mockResolvedValueOnce(Response.json(studioAccess));

    await expect(
      loadAdminSession(fetcher, controller.signal),
    ).resolves.toMatchObject({
      personId,
      sessionId,
      tenantId,
      permissions: expect.arrayContaining(["admin_surface"]),
    });
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
      "/v1/me",
      "/v1/context",
      "/v1/me/studio-access",
    ]);
    expect(
      fetcher.mock.calls.every(
        ([, init]) =>
          init?.credentials === "same-origin" &&
          init.signal === controller.signal,
      ),
    ).toBe(true);
  });

  it.each([
    ["missing admin permission", { ...context, permissions: [] }],
    ["learner role", { ...context, membership_role: "learner" }],
    ["missing tenant", { ...context, tenant_id: null }],
    ["identity mismatch", { ...context, person_id: sessionId }],
  ])("fails closed for %s", async (_label, invalidContext) => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(me))
      .mockResolvedValueOnce(Response.json(invalidContext))
      .mockResolvedValueOnce(Response.json(studioAccess));

    await expect(loadAdminSession(fetcher)).rejects.toMatchObject({
      code: "admin_session_denied",
    });
  });

  it("fails closed when /v1/me omits admin_surface even if /v1/context claims it", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ ...me, permissions: [] }))
      .mockResolvedValueOnce(Response.json(context))
      .mockResolvedValueOnce(Response.json(studioAccess));

    await expect(loadAdminSession(fetcher)).rejects.toMatchObject({
      code: "admin_session_denied",
    });
  });

  it("reads and validates the three tenant-derived Studio resources", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(studioReadinessResponse))
      .mockResolvedValueOnce(Response.json(studioProgramsResponse))
      .mockResolvedValueOnce(Response.json(studioProgramResponse));

    await expect(loadStudioReadiness(fetcher)).resolves.toMatchObject({
      tenant_id: tenantId,
      draft_backlog_count: 1,
      arrival_rate: { status: "unavailable", value: null },
    });
    await expect(loadStudioPrograms(fetcher)).resolves.toMatchObject({
      tenant_id: tenantId,
      programs: [{ id: programId, access: "selected_tenant" }],
    });
    await expect(loadStudioProgram(programId, fetcher)).resolves.toMatchObject({
      tenant_id: tenantId,
      id: programId,
      versions: [{ id: versionId, etag: versionEtag }],
    });

    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
      "/v1/admin/studio/readiness",
      "/v1/admin/studio/programs",
      `/v1/admin/studio/programs/${programId}`,
    ]);
    expect(
      fetcher.mock.calls.every(
        ([, init]) =>
          new Headers(init?.headers).get("idempotency-key") === null,
      ),
    ).toBe(true);
  });

  it("does not accept caller-provided role or tenant headers", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(publishResponse));
    await publishProgramVersion({
      programVersionId: versionId,
      reason: "approved release",
      ifMatch: versionEtag,
      idempotencyKey: publishCommandKey,
      origin: "https://admin-staging.authorityclosers.com",
      fetcher,
    });

    const [, init] = fetcher.mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);
    expect(headers.get("x-admin-role")).toBeNull();
    expect(headers.get("x-tenant-id")).toBeNull();
  });

  it("sends the exact publish payload and same-surface Origin", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(publishResponse));
    await publishProgramVersion({
      programVersionId: versionId,
      reason: "approved release",
      ifMatch: versionEtag,
      idempotencyKey: publishCommandKey,
      origin: "https://admin-staging.authorityclosers.com",
      fetcher,
    });

    const [url, init] = fetcher.mock.calls[0];
    expect(String(url)).toBe(`/v1/admin/program-versions/${versionId}/publish`);
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("origin")).toBe(
      "https://admin-staging.authorityclosers.com",
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      reason: "approved release",
    });
    expect(headers.get("idempotency-key")).toBe(publishCommandKey);
    expect(headers.get("if-match")).toBe(versionEtag);
  });

  it("sends idempotency and If-Match only where the contracts require them", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(correctionResponse))
      .mockResolvedValueOnce(Response.json(grantResponse))
      .mockResolvedValueOnce(Response.json(retryResponse))
      .mockResolvedValueOnce(Response.json(reconcileResponse));
    await appendCorrection({
      submissionId,
      decision: "approved",
      reason: "reviewed evidence",
      ifMatch: '"submission-revision-4"',
      idempotencyKey: "correction-command-1",
      origin: "https://admin-staging.authorityclosers.com",
      fetcher,
    });
    await grantEnrollment({
      personId,
      programVersionId: versionId,
      reason: "support grant",
      idempotencyKey: "grant-command-1",
      origin: "https://admin-staging.authorityclosers.com",
      fetcher,
    });
    await retryJob({
      jobId,
      reason: "retry after operator review",
      idempotencyKey: "retry-command-1",
      origin: "https://admin-staging.authorityclosers.com",
      fetcher,
    });
    await reconcileRecovery({
      jobIds: [jobId],
      outboxEventIds: [outboxId],
      reason: "release reviewed set",
      idempotencyKey: "reconcile-command-1",
      origin: "https://admin-staging.authorityclosers.com",
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledTimes(4);
    const correctionHeaders = new Headers(fetcher.mock.calls[0][1]?.headers);
    expect(correctionHeaders.get("idempotency-key")).toBe(
      "correction-command-1",
    );
    expect(correctionHeaders.get("if-match")).toBe('"submission-revision-4"');
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      submission_id: submissionId,
      decision: "approved",
      reason: "reviewed evidence",
    });
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({
      person_id: personId,
      program_version_id: versionId,
      reason: "support grant",
    });
    expect(JSON.parse(String(fetcher.mock.calls[3][1]?.body))).toEqual({
      job_ids: [jobId],
      outbox_event_ids: [outboxId],
      reason: "release reviewed set",
    });
  });

  it("surfaces bounded problem responses without pretending a mutation succeeded", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          type: "https://authorityclosers.com/problems/admin-authorization-denied",
          title: "Admin authorization denied",
          status: 403,
          detail: "The actor lacks the required permission.",
          code: "admin_authorization_denied",
          request_id: "req-123",
        }),
        {
          status: 403,
          headers: { "content-type": "application/problem+json" },
        },
      ),
    );

    await expect(
      grantEnrollment({
        personId,
        programVersionId: versionId,
        reason: "support grant",
        idempotencyKey: "grant-command-2",
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
    ).rejects.toMatchObject({
      status: 403,
      code: "admin_authorization_denied",
      requestId: "req-123",
    });
  });

  it("rejects a malformed successful mutation response", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ status: "published" }));

    await expect(
      publishProgramVersion({
        programVersionId: versionId,
        reason: "approved release",
        ifMatch: versionEtag,
        idempotencyKey: publishCommandKey,
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
    ).rejects.toThrow();
  });

  it.each(mutationAdapters)(
    "%s validates and rejects an empty 204 response",
    async (_label, invoke) => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(null, { status: 204 }));

      await expect(invoke(fetcher)).rejects.toThrow();
      expect(fetcher).toHaveBeenCalledOnce();
    },
  );

  it("validates and rejects an empty successful body", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 200 }));

    await expect(
      publishProgramVersion({
        programVersionId: versionId,
        reason: "approved release",
        ifMatch: versionEtag,
        idempotencyKey: publishCommandKey,
        origin: "https://admin-staging.authorityclosers.com",
        fetcher,
      }),
    ).rejects.toThrow();
  });
});
