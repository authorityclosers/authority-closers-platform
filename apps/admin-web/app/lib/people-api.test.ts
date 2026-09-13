import { describe, expect, it, vi } from "vitest";
import {
  AdminApiProblem,
  lookupAdminLearners,
  loadAdminLearnerDiagnosis,
  loadMemberDirectory,
} from "./admin-api";
import {
  diagnosis,
  lookup,
  otherId,
  personId,
  tenantId,
} from "../../test-fixtures/people";

const options = {
  tenantId,
  purpose: "learner_support" as const,
  origin: "https://admin.example.test",
};
function response(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

it("keeps the exact lookup key in a same-origin POST body with no client authority", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(lookup));
  const signal = new AbortController().signal;
  expect(
    await lookupAdminLearners({
      ...options,
      query: " learner@example.test ",
      fetcher,
      signal,
    }),
  ).toEqual(lookup);
  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe("/v1/admin/learners/lookup");
  expect(init).toMatchObject({
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  expect(JSON.parse(String(init?.body))).toEqual({
    query: "learner@example.test",
    purpose: "learner_support",
  });
  expect(new Headers(init?.headers).get("origin")).toBe(options.origin);
});

it("loads a bounded directory without exposing search input in the URL", async () => {
  const page = {
    tenant_id: tenantId,
    tenant_name: "Academy",
    members: [],
    summary: { total: 0, active_learners: 0, team: 0, unverified: 0 },
    matching_count: 0,
    page: 1,
    page_size: 25,
  };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(page));
  await expect(
    loadMemberDirectory({ ...options, filters: { query: " Suy " }, fetcher }),
  ).resolves.toEqual(page);
  expect(fetcher.mock.calls[0][0]).toBe("/v1/admin/people/directory");
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
    query: "Suy",
    role: "all",
    status: "all",
    page: 1,
    page_size: 25,
  });
  for (const changed of [
    { tenant_id: otherId },
    { page: 2 },
    { matching_count: 4 },
  ]) {
    fetcher.mockResolvedValueOnce(response({ ...page, ...changed }));
    await expect(
      loadMemberDirectory({ ...options, fetcher }),
    ).rejects.toThrow();
  }
});

it("loads a selected learner diagnosis with only its declared purpose", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(diagnosis));
  await expect(
    loadAdminLearnerDiagnosis({ ...options, personId, fetcher }),
  ).resolves.toEqual(diagnosis);
  expect(fetcher.mock.calls[0][0]).toBe(
    `/v1/admin/learners/${personId}/diagnosis?purpose=learner_support`,
  );
  expect(fetcher.mock.calls[0][1]).toMatchObject({
    method: "GET",
    cache: "no-store",
    credentials: "same-origin",
  });
});

describe("strictly binds returned private records", () => {
  it.each([
    { ...diagnosis, tenant_id: otherId },
    { ...diagnosis, person_id: otherId },
    { ...diagnosis, purpose: "accessibility_review" },
    { ...diagnosis, email: "unredacted@example.test" },
    {
      ...diagnosis,
      enrollments: [
        {
          ...diagnosis.enrollments[0],
          drafts: [
            {
              ...diagnosis.enrollments[0].drafts[0],
              payload: { private: "content" },
            },
          ],
        },
      ],
    },
    {
      ...diagnosis,
      enrollments: [
        {
          ...diagnosis.enrollments[0],
          progress: {
            ...diagnosis.enrollments[0].progress,
            completed_count: 6,
          },
        },
      ],
    },
  ])("rejects scope, redaction or count violations", async (value) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(value));
    await expect(
      loadAdminLearnerDiagnosis({ ...options, personId, fetcher }),
    ).rejects.toThrow();
  });
  it("rejects a lookup from another academy", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response({ ...lookup, tenant_id: otherId }));
    await expect(
      lookupAdminLearners({ ...options, query: "learner", fetcher }),
    ).rejects.toThrow();
  });
  it.each([
    "",
    "aa",
    personId,
    "00000000-0000-0000-0000-000000000000",
    "a".repeat(321),
  ])("rejects invalid lookup before I/O", (query) => {
    const fetcher = vi.fn<typeof fetch>();
    expect(() => lookupAdminLearners({ ...options, query, fetcher })).toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("preserves declared HTTP failures", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ code: "scope_denied", detail: "Denied" }),
          { status: 403 },
        ),
      );
    await expect(
      loadAdminLearnerDiagnosis({ ...options, personId, fetcher }),
    ).rejects.toBeInstanceOf(AdminApiProblem);
  });
});
