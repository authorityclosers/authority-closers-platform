import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildAcademyReviewLink,
  createReviewAssignment,
  loadReviewAssignments,
  reviewError,
  revokeReviewAssignment,
} from "./review-api";

const ids = {
  assignment: "11111111-1111-4111-8111-111111111111",
  tenant: "22222222-2222-4222-8222-222222222222",
  run: "33333333-3333-4333-8333-333333333333",
  reviewer: "44444444-4444-4444-8444-444444444444",
  actor: "55555555-5555-4555-8555-555555555555",
  recording: "66666666-6666-4666-8666-666666666666",
  permission: "77777777-7777-4777-8777-777777777777",
  checkpoint: "88888888-8888-4888-8888-888888888888",
};
const digest = "a".repeat(64);

const assignment = {
  schema_id: "ac.sales-xray.review-assignment/1" as const,
  id: ids.assignment,
  tenant_id: ids.tenant,
  run_id: ids.run,
  run_generation: 2,
  recipe_revision: "recipe-v1",
  source: {
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    permission_id: ids.permission,
    provenance_ref:
      "ref:conversation-permission:77777777-7777-4777-8777-777777777777",
  },
  checkpoint: {
    id: ids.checkpoint,
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    stage: "C2" as const,
    revision: "checkpoint-v1",
    cache_key: digest,
    manifest_sha256: digest,
    payload_sha256: digest,
  },
  reviewer_person_id: ids.reviewer,
  allowed_lenses: ["sales", "technical"] as const,
  state: "assigned" as const,
  created_at_epoch: 1_800_000_000,
  expires_at_epoch: 1_800_086_400,
  created_by_person_id: ids.actor,
};
const { schema_id: schemaId, ...assignmentFields } = assignment;
const wireAssignment = { schema: schemaId, ...assignmentFields };

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("review assignment API boundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("loads the bounded server queue with a private same-origin request", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ items: [wireAssignment] }));

    await expect(loadReviewAssignments(fetcher)).resolves.toEqual({
      items: [assignment],
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/admin/conversation/review-assignments?limit=50",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
      }),
    );
  });

  it("sends the exact create DTO and preserves the caller's idempotency key", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(wireAssignment, 201));

    await createReviewAssignment({
      runId: ids.run,
      reviewerPersonId: ids.reviewer,
      allowedLenses: ["sales", "technical"],
      expiresAtEpoch: assignment.expires_at_epoch,
      idempotencyKey: "create-review-1",
      origin: "https://admin.authorityclosers.com",
      fetcher,
    });

    const [path, init] = fetcher.mock.calls[0] ?? [];
    expect(path).toBe("/v1/admin/conversation/review-assignments");
    expect((init?.headers as Headers).get("Idempotency-Key")).toBe(
      "create-review-1",
    );
    expect((init?.headers as Headers).get("origin")).toBe(
      "https://admin.authorityclosers.com",
    );
    expect(JSON.parse(init?.body as string)).toEqual({
      schema: "ac.sales-xray.review-assignment-create/1",
      run_id: ids.run,
      reviewer_person_id: ids.reviewer,
      allowed_lenses: ["sales", "technical"],
      expires_at_epoch: assignment.expires_at_epoch,
    });
  });

  it.each([
    { run_id: ids.recording },
    { reviewer_person_id: ids.actor },
    { allowed_lenses: ["ux"] },
    { expires_at_epoch: assignment.expires_at_epoch + 1 },
  ])(
    "rejects a create receipt with a mismatched $run_id$reviewer_person_id$allowed_lenses$expires_at_epoch binding",
    async (change) => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse({ ...wireAssignment, ...change }, 201));

      await expect(
        createReviewAssignment({
          runId: ids.run,
          reviewerPersonId: ids.reviewer,
          allowedLenses: ["sales", "technical"],
          expiresAtEpoch: assignment.expires_at_epoch,
          idempotencyKey: "create-review-mismatch",
          fetcher,
        }),
      ).rejects.toThrow("does not match the requested reviewer handoff");
      expect(
        reviewError(
          await createReviewAssignment({
            runId: ids.run,
            reviewerPersonId: ids.reviewer,
            allowedLenses: ["sales", "technical"],
            expiresAtEpoch: assignment.expires_at_epoch,
            idempotencyKey: "create-review-mismatch",
            fetcher: vi
              .fn<typeof fetch>()
              .mockResolvedValue(
                jsonResponse({ ...wireAssignment, ...change }, 201),
              ),
          }).catch((error: unknown) => error),
        ),
      ).toEqual({
        message:
          "The server returned an assignment that does not match the requested reviewer handoff.",
        retryable: false,
      });
    },
  );

  it("posts revoke to the assignment UUID route and validates the direct assignment response", async () => {
    const revoked = { ...assignment, state: "revoked" as const };
    const { schema_id: revokedSchemaId, ...revokedFields } = revoked;
    const wireRevoked = { schema: revokedSchemaId, ...revokedFields };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(wireRevoked));

    await expect(
      revokeReviewAssignment({
        assignmentId: ids.assignment,
        idempotencyKey: "revoke-review-1",
        origin: "https://admin.authorityclosers.com",
        fetcher,
      }),
    ).resolves.toEqual(revoked);
    const [path, init] = fetcher.mock.calls[0] ?? [];
    expect(path).toBe(
      `/v1/admin/conversation/review-assignments/${ids.assignment}/revoke`,
    );
    expect((init?.headers as Headers).get("Idempotency-Key")).toBe(
      "revoke-review-1",
    );
    expect(init?.body).toBeUndefined();
  });

  it.each([{ id: ids.run }, { state: "assigned" }])(
    "rejects a revoke receipt that is not the confirmed revoked assignment",
    async (change) => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse({ ...wireAssignment, ...change }));

      await expect(
        revokeReviewAssignment({
          assignmentId: ids.assignment,
          idempotencyKey: "revoke-review-mismatch",
          fetcher,
        }),
      ).rejects.toThrow("did not confirm revocation");
    },
  );

  it("builds Academy links only from the configured origin", () => {
    expect(
      buildAcademyReviewLink(
        "https://learner.authorityclosers.com",
        ids.assignment,
      ),
    ).toBe(
      `https://learner.authorityclosers.com/sales-xray/review/${ids.assignment}`,
    );
    expect(buildAcademyReviewLink(undefined, ids.assignment)).toBeNull();
    expect(
      buildAcademyReviewLink("https://evil.example", ids.assignment),
    ).toBeNull();
  });

  it("keeps terminal bridge errors terminal while allowing transport retry", () => {
    expect(
      reviewError(
        Object.assign(new Error("Permission denied."), { retryable: false }),
      ),
    ).toEqual({ message: "Permission denied.", retryable: false });
    expect(reviewError(new Error("temporary upstream failure"))).toEqual({
      message: "temporary upstream failure",
      retryable: true,
    });
  });
});
