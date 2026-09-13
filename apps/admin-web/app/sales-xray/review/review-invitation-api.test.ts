import { describe, expect, it, vi } from "vitest";

import {
  createReviewInvitation,
  revokeReviewInvitation,
} from "./review-invitation-api";

const run = "30000000-0000-4000-8000-000000000003";
const invitation = "90000000-0000-4000-8000-000000000009";

function receipt(state: "pending" | "revoked") {
  return {
    id: invitation,
    run_id: run,
    invited_email: "reviewer@example.test",
    allowed_lenses: ["sales", "technical", "ux"],
    created_at_epoch: 100,
    expires_at_epoch: 200,
    state,
    assignment_id: null,
  };
}

describe("review invitation API boundary", () => {
  it("sends only the exact invitation intent and reports queued delivery", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(receipt("pending")), { status: 201 }),
      );
    const result = await createReviewInvitation({
      runId: run,
      invitedEmail: "Reviewer@Example.test",
      allowedLenses: ["sales", "technical", "ux"],
      expiresAtEpoch: 200,
      idempotencyKey: "invite-1",
      origin: "https://admin.example.test",
      fetcher,
    });
    expect(result.state).toBe("pending");
    const [, init] = fetcher.mock.calls[0]!;
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("invite-1");
    expect(JSON.parse(String(init?.body))).toEqual({
      schema: "ac.sales-xray.review-invitation-create/1",
      run_id: run,
      invited_email: "Reviewer@Example.test",
      allowed_lenses: ["sales", "technical", "ux"],
      expires_at_epoch: 200,
    });
    expect(String(init?.body)).not.toContain("token");
  });

  it("revokes a server-known invitation with a separate idempotent command", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(receipt("revoked")), { status: 200 }),
      );
    const result = await revokeReviewInvitation({
      invitationId: invitation,
      idempotencyKey: "revoke-1",
      origin: "https://admin.example.test",
      fetcher,
    });
    expect(result.state).toBe("revoked");
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      `/v1/admin/conversation/review-invitations/${invitation}/revoke`,
    );
  });

  it.each([
    { run_id: "30000000-0000-4000-8000-000000000004" },
    { invited_email: "different@example.test" },
    { allowed_lenses: ["sales", "technical", "technical"] },
    { expires_at_epoch: 201 },
  ])("rejects mismatched create receipts: %j", async (changed) => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...receipt("pending"), ...changed }), {
        status: 201,
      }),
    );
    await expect(
      createReviewInvitation({
        runId: run,
        invitedEmail: "reviewer@example.test",
        allowedLenses: ["sales", "technical", "ux"],
        expiresAtEpoch: 200,
        idempotencyKey: "create-mismatch",
        fetcher,
      }),
    ).rejects.toThrow();
  });

  it.each([
    { id: "90000000-0000-4000-8000-000000000008" },
    { state: "pending" },
  ])("rejects an unconfirmed revocation: %j", async (changed) => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...receipt("revoked"), ...changed }), {
        status: 200,
      }),
    );
    await expect(
      revokeReviewInvitation({
        invitationId: invitation,
        idempotencyKey: "revoke-mismatch",
        fetcher,
      }),
    ).rejects.toThrow();
  });
});
