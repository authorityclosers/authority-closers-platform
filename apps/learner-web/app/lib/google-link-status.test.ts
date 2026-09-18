import { describe, expect, it, vi } from "vitest";

import { createLearnerApi, parseGoogleLinkStatusResponse } from "./learner-api";

describe("Google-link status API", () => {
  it("reads the canonical boolean with same-origin credentials and no-store cache", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(JSON.stringify({ linked: true, person_id: "private" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const api = createLearnerApi(fetcher, { offlineReadCache: null });

    await expect(api.googleLinkStatus()).resolves.toEqual({ linked: true });
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/me/google-link",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
      }),
    );
  });

  it.each([null, [], {}, { linked: "true" }, { linked: 1 }])(
    "rejects a non-boolean canonical response: %j",
    (body) => {
      expect(() => parseGoogleLinkStatusResponse(body)).toThrow(
        "invalid Google-link status",
      );
    },
  );
});
