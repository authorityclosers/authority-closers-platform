import { describe, expect, it, vi } from "vitest";

import {
  acceptReviewerInvitation,
  createReviewerAssignmentApi,
} from "./reviewer-api";

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
    provenance_ref: "ref:permission:77777777-7777-4777-8777-777777777777",
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
  allowed_lenses: ["sales", "technical"],
  state: "assigned",
  created_at_epoch: 1_800_000_000,
  expires_at_epoch: 1_800_086_400,
  created_by_person_id: ids.actor,
};

describe("reviewer assignment transport", () => {
  it("loads only the reviewer-scoped bounded queue", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ items: [assignment], truncated: false }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    await expect(createReviewerAssignmentApi(fetcher).queue()).resolves.toEqual(
      { items: [assignment], truncated: false },
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/reviewer/review-assignments?limit=50",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      }),
    );
  });

  it("accepts an invitation into the reviewer audience and returns only the assignment envelope", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(assignment), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(
      acceptReviewerInvitation("i".repeat(43), fetcher),
    ).resolves.toEqual(assignment);
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/reviewer/review-invitations/accept",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
    expect(
      JSON.parse((fetcher.mock.calls[0]?.[1]?.body ?? "{}") as string),
    ).toEqual({
      schema: "ac.sales-xray.review-invitation-accept/1",
      token: "i".repeat(43),
    });
  });
});
