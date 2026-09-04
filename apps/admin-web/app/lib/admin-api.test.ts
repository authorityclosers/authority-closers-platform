import { afterEach, describe, expect, it, vi } from "vitest";

import {
  appendCorrection,
  grantEnrollment,
  loadAdminSession,
  loadStudioProgram,
  loadStudioPrograms,
  loadStudioReadiness,
  publishProgramVersion,
  reconcileRecovery,
  retryJob,
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

describe("same-origin admin API composition", () => {
  it("requires both canonical product identity and selected admin context", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(me))
      .mockResolvedValueOnce(Response.json(context));

    await expect(loadAdminSession(fetcher)).resolves.toMatchObject({
      personId,
      sessionId,
      tenantId,
      permissions: expect.arrayContaining(["admin_surface"]),
    });
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
      "/v1/me",
      "/v1/context",
    ]);
    expect(
      fetcher.mock.calls.every(
        ([, init]) => init?.credentials === "same-origin",
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
      .mockResolvedValueOnce(Response.json(invalidContext));

    await expect(loadAdminSession(fetcher)).rejects.toMatchObject({
      code: "admin_session_denied",
    });
  });

  it("fails closed when /v1/me omits admin_surface even if /v1/context claims it", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ ...me, permissions: [] }))
      .mockResolvedValueOnce(Response.json(context));

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
