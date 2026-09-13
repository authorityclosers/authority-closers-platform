import { describe, expect, it, vi } from "vitest";

import {
  adminReviewDetailsError,
  loadAdminReviewDetails,
} from "./admin-review-details-api";

const ids = {
  assignment: "11111111-1111-4111-8111-111111111111",
  tenant: "22222222-2222-4222-8222-222222222222",
  run: "33333333-3333-4333-8333-333333333333",
  reviewer: "44444444-4444-4444-8444-444444444444",
  recording: "66666666-6666-4666-8666-666666666666",
  permission: "77777777-7777-4777-8777-777777777777",
  checkpoint: "88888888-8888-4888-8888-888888888888",
  feedback: "99999999-9999-4999-8999-999999999999",
};
const digest = "a".repeat(64);

const assignment = {
  schema: "ac.sales-xray.review-assignment/1",
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
    provenance_ref: `ref:conversation-permission:${ids.permission}`,
  },
  checkpoint: {
    id: ids.checkpoint,
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    stage: "C2",
    revision: "checkpoint-v1",
    cache_key: digest,
    manifest_sha256: digest,
    payload_sha256: digest,
  },
  reviewer_person_id: ids.reviewer,
  allowed_lenses: ["sales"],
  state: "submitted",
  created_at_epoch: 1_800_000_000,
  expires_at_epoch: 1_800_086_400,
  created_by_person_id: ids.reviewer,
};

const details = {
  assignment,
  lifecycle: {
    state: "submitted",
    created_at_epoch: 1_800_000_000,
    expires_at_epoch: 1_800_086_400,
    revocation: null,
  },
  source: {
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    state: "ready",
    content_state: "retained",
    permission_expires_at_epoch: 1_800_086_400,
    retention_until_epoch: 1_800_086_400,
    permission_revoked_at_epoch: null,
  },
  review: {
    run_id: ids.run,
    run_generation: 2,
    recipe_revision: "recipe-v1",
    run_state: "completed",
    report_id: ids.run,
    report_state: "retained",
    checkpoint_id: ids.checkpoint,
    checkpoint_state: "retained",
  },
  feedback: [
    {
      id: ids.feedback,
      assignment_id: ids.assignment,
      tenant_id: ids.tenant,
      request_sha256: digest,
      payload_sha256: digest,
      created_at_epoch: 1_800_000_001,
      erased_at_epoch: null,
      state: "available",
      payload: {
        schema: "ac.sales-xray.review-feedback/1",
        id: ids.feedback,
        assignment_id: ids.assignment,
        tenant_id: ids.tenant,
        run_id: ids.run,
        reviewer_person_id: ids.reviewer,
        author_person_id: ids.reviewer,
        lens: "sales",
        lane: "sales",
        idempotency_key: "feedback-1",
        request_sha256: digest,
        evidence_refs: [
          { checkpoint_id: ids.checkpoint, span_id: "segment-1" },
        ],
        confidence: "high",
        feedback: "The opening established the buyer context.",
        proposed_correction: null,
        created_at_epoch: 1_800_000_001,
      },
    },
  ],
  feedback_count: 1,
  available_feedback_count: 1,
  feedback_truncated: false,
};

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("Admin review detail API", () => {
  it("rejects a different assignment and mismatched feedback bindings", async () => {
    for (const bad of [
      { ...details, assignment: { ...assignment, id: ids.run } },
      {
        ...details,
        feedback: [{ ...details.feedback[0], tenant_id: ids.run }],
      },
      { ...details, review: { ...details.review, run_id: ids.assignment } },
    ]) {
      await expect(
        loadAdminReviewDetails(
          ids.assignment,
          vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(bad)),
        ),
      ).rejects.toThrow("does not match");
    }
  });
  it("loads exact assignment details through a private same-origin GET", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(details));

    const loaded = await loadAdminReviewDetails(ids.assignment, fetcher);
    expect(loaded.feedback[0]?.payload?.feedback).toBe(
      "The opening established the buyer context.",
    );
    expect(fetcher).toHaveBeenCalledWith(
      `/v1/admin/conversation/review-assignments/${ids.assignment}`,
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        mode: "same-origin",
      }),
    );
  });

  it("rejects malformed IDs and redaction violations before rendering", async () => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(loadAdminReviewDetails("not-an-id", fetcher)).rejects.toThrow(
      "assignmentId must be a UUID",
    );
    expect(fetcher).not.toHaveBeenCalled();

    const malformed = {
      ...details,
      feedback: [
        {
          ...details.feedback[0],
          state: "erased",
          payload: details.feedback[0]?.payload,
        },
      ],
    };
    await expect(
      loadAdminReviewDetails(
        ids.assignment,
        vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(malformed)),
      ),
    ).rejects.toThrow();
  });

  it("keeps server denial retry semantics", async () => {
    const response = jsonResponse(
      { detail: "The admin surface is required." },
      403,
    );
    await expect(
      loadAdminReviewDetails(
        ids.assignment,
        vi.fn<typeof fetch>().mockResolvedValue(response),
      ),
    ).rejects.toMatchObject({ status: 403 });
    expect(adminReviewDetailsError(new Error("temporary outage"))).toEqual({
      message: "temporary outage",
      retryable: true,
    });
  });
});
