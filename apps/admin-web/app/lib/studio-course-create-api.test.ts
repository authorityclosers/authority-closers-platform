import { expect, it, vi } from "vitest";
import {
  createStudioCourse,
  type StudioDraftMutationResponse,
} from "@ac/operations-web/api";

const tenantId = "11111111-1111-4111-8111-111111111111";
const programId = "22222222-2222-4222-8222-222222222222";
const versionId = "33333333-3333-4333-8333-333333333333";
function receipt(): StudioDraftMutationResponse {
  return {
    resource_id: versionId,
    replayed: false,
    program: {
      tenant_id: tenantId,
      id: programId,
      slug: "new-course",
      title: "New course",
      scope: "tenant",
      access: "selected_tenant",
      versions_truncated: false,
      versions: [
        {
          id: versionId,
          version_number: 1,
          status: "draft",
          created_at: "2026-09-09T00:00:00Z",
          published_at: null,
          supersedes_version_id: null,
          content_source_ref: null,
          content_reviewed_by: null,
          content_reviewed_at: null,
          release_id: null,
          content_seed_kind: null,
          content_digest: null,
          etag: '"program-version-' + "a".repeat(64) + '"',
          readiness: "blocked",
          blockers: ["provenance_incomplete"],
          modules: [],
        },
      ],
    },
  };
}
const input = {
  title: " New course ",
  tenantId,
  idempotencyKey: "bounded-key",
  origin: "http://coach.localhost:3102",
};
it("posts only the name with canonical command headers and validates its receipt", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(Response.json(receipt()));
  const result = await createStudioCourse({ ...input, fetcher });
  expect(result.resource_id).toBe(versionId);
  expect(fetcher.mock.calls[0][0]).toBe("/v1/admin/studio/programs");
  const options = fetcher.mock.calls[0][1]!;
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body as string)).toEqual({ title: "New course" });
  const headers = new Headers(options.headers);
  expect(headers.get("Idempotency-Key")).toBe("bounded-key");
  expect(headers.get("If-Match")).toBeNull();
  expect(options.cache).toBe("no-store");
});
it.each([
  "tenant",
  "scope",
  "resource",
  "duplicate",
  "version",
  "title",
  "published",
])("rejects a contradictory %s receipt", async (kind) => {
  const result = receipt();
  if (kind === "tenant") result.program.tenant_id = programId;
  if (kind === "scope") result.program.scope = "global";
  if (kind === "resource") result.resource_id = programId;
  if (kind === "duplicate")
    result.program.versions.push({ ...result.program.versions[0] });
  if (kind === "version") result.program.versions[0].version_number = 2;
  if (kind === "title") result.program.title = "Another course";
  if (kind === "published") result.program.versions[0].status = "published";
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(Response.json(result));
  await expect(createStudioCourse({ ...input, fetcher })).rejects.toThrow();
});
it("permits an exact older receipt whose version has subsequently been published", async () => {
  const result = receipt();
  result.replayed = true;
  result.program.versions[0].status = "published";
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(Response.json(result));
  expect((await createStudioCourse({ ...input, fetcher })).replayed).toBe(true);
});
it.each(["", " ", "x".repeat(129), "\nkey", "key\u007f"])(
  "rejects invalid command key before network %j",
  (idempotencyKey) => {
    const fetcher = vi.fn<typeof fetch>();
    expect(() =>
      createStudioCourse({ ...input, idempotencyKey, fetcher }),
    ).toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  },
);
