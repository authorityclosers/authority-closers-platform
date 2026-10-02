import { expect, it, vi } from "vitest";
import { z } from "zod";
import { AdminApiProblem } from "./admin-api";
import {
  loadPlatformOrganisations,
  platformOrganisationsSchema,
} from "./organisations-api";

const organisation = {
  tenant_id: "11111111-1111-4111-8111-111111111111",
  name: "Fictional Example Organisation",
  member_count: 0,
  created_at: "2026-10-02T00:00:00Z",
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

it.each([{ organisations: [organisation] }, { organisations: [] }])(
  "loads a valid directory: %j",
  async (payload) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(payload));
    const signal = new AbortController().signal;
    await expect(
      loadPlatformOrganisations({ fetcher, signal }),
    ).resolves.toEqual(payload);
    expect(platformOrganisationsSchema.parse(payload)).toEqual(payload);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith(
      "/v1/platform/organisations",
      {
        method: "GET",
        headers: { accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal,
      },
    );
  },
);

it.each([
  null,
  {},
  { organisations: [], extra: true },
  { organisations: [{ ...organisation, extra: true }] },
  ...[
    { tenant_id: "invalid" },
    { member_count: -1 },
    { member_count: 1.5 },
    { member_count: "1" },
    { name: "" },
    { created_at: "" },
  ].map((invalid) => ({ organisations: [{ ...organisation, ...invalid }] })),
])("rejects malformed directory payloads: %j", async (payload) => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(payload));
  await expect(loadPlatformOrganisations({ fetcher })).rejects.toBeInstanceOf(
    z.ZodError,
  );
});

it.each([
  [401, "Fictional session expired."],
  [403, "Organisation access denied."],
  [404, "Fictional organisation directory not found."],
  [409, "Organisation changed. Reload and try again."],
] as const)("preserves the server problem for %i", async (status, detail) => {
  const problem = {
    code: "fictional_problem",
    title: "Rejected",
    detail,
    request_id: "fictional-request",
  };
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(json(problem, status));
  const error = await loadPlatformOrganisations({ fetcher }).catch((e) => e);
  expect(error).toBeInstanceOf(AdminApiProblem);
  expect(error).toMatchObject({
    status,
    code: problem.code,
    title: problem.title,
    message: detail,
    requestId: problem.request_id,
  });
});

it("propagates transport failures and rejects invalid success JSON", async () => {
  const failure = new TypeError("Fictional network failure");
  const fetcher = vi.fn<typeof fetch>().mockRejectedValue(failure);
  await expect(loadPlatformOrganisations({ fetcher })).rejects.toBe(failure);
  fetcher.mockResolvedValue(new Response("invalid JSON"));
  await expect(loadPlatformOrganisations({ fetcher })).rejects.toBeInstanceOf(
    z.ZodError,
  );
});
