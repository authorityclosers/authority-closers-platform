import { describe, expect, it, vi } from "vitest";

import { acceptReviewInvitation } from "./review-invitation-api";

const token = "invite-token-" + "a".repeat(48);
const ids = {
  tenant: "10000000-0000-4000-8000-000000000001",
  recording: "20000000-0000-4000-8000-000000000002",
  run: "30000000-0000-4000-8000-000000000003",
  assignment: "40000000-0000-4000-8000-000000000004",
  checkpoint: "50000000-0000-4000-8000-000000000005",
  reviewer: "60000000-0000-4000-8000-000000000006",
  permission: "70000000-0000-4000-8000-000000000007",
};

function assignment() {
  return {
    schema: "ac.sales-xray.review-assignment/1",
    id: ids.assignment,
    tenant_id: ids.tenant,
    run_id: ids.run,
    run_generation: 3,
    recipe_revision: "audioatlas-48000-v1",
    source: {
      tenant_id: ids.tenant,
      recording_id: ids.recording,
      source_sha256: "a".repeat(64),
      source_revision: 1,
      permission_id: ids.permission,
      provenance_ref: `ref:conversation-permission:${ids.permission}`,
    },
    checkpoint: {
      id: ids.checkpoint,
      tenant_id: ids.tenant,
      recording_id: ids.recording,
      source_sha256: "a".repeat(64),
      source_revision: 1,
      stage: "C2",
      revision: "b".repeat(64),
      cache_key: "c".repeat(64),
      manifest_sha256: "d".repeat(64),
      payload_sha256: "e".repeat(64),
    },
    reviewer_person_id: ids.reviewer,
    allowed_lenses: ["sales", "technical", "ux"],
    state: "assigned",
    created_at_epoch: 100,
    expires_at_epoch: 200,
    created_by_person_id: ids.reviewer,
  };
}

describe("review invitation acceptance API", () => {
  it("posts the versioned token body and accepts only the server assignment", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(assignment()), { status: 201 }),
      );
    const result = await acceptReviewInvitation(token, fetcher);
    expect(result.id).toBe(ids.assignment);
    const [path, init] = fetcher.mock.calls[0]!;
    expect(path).toBe("/v1/conversation/review-invitations/accept");
    expect(JSON.parse(String(init?.body))).toEqual({
      schema: "ac.sales-xray.review-invitation-accept/1",
      token,
    });
    expect(String(path)).not.toContain(token);
  });

  it("keeps unauthenticated and invalid invitations generic", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "Review invitation not found." }),
          { status: 404 },
        ),
      );
    await expect(acceptReviewInvitation(token, fetcher)).rejects.toMatchObject({
      status: 404,
    });
    await expect(
      acceptReviewInvitation("too short", fetcher),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
