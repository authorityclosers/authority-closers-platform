import { afterEach, describe, expect, it, vi } from "vitest";

import {
  readReviewerToken,
  requestReviewerSignIn,
  verifyReviewerSignIn,
  withReviewerToken,
} from "./reviewer-auth";

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("reviewer mailbox boundary", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps the invitation token in a fragment and sends it only to the reviewer request endpoint", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response({ status: "check_email" }, 202));
    vi.stubGlobal("fetch", fetcher);
    const token = "review-token-" + "r".repeat(40);
    expect(readReviewerToken(`#token=${encodeURIComponent(token)}`)).toBe(
      token,
    );
    expect(withReviewerToken("/reviewer/verify", token)).toBe(
      `/reviewer/verify#token=${encodeURIComponent(token)}`,
    );
    await requestReviewerSignIn("Reviewer@Example.com", token);
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/reviewer/auth/request",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
    expect(
      JSON.parse((fetcher.mock.calls[0]?.[1]?.body ?? "{}") as string),
    ).toEqual({ email: "reviewer@example.com", invitation_token: token });
  });

  it("accepts only the dedicated reviewer verification response shape", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      response({
        person_id: "11111111-1111-4111-8111-111111111111",
        email: "reviewer@example.com",
        display_name: "Reviewer",
        expires_at_epoch: 1_800_000_000,
        assignment_id: null,
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    await expect(
      verifyReviewerSignIn("verify-token-" + "v".repeat(40)),
    ).resolves.toMatchObject({
      assignment_id: null,
      email: "reviewer@example.com",
    });
    expect(fetcher.mock.calls[0]?.[0]).toBe("/v1/reviewer/auth/verify");
  });
});
