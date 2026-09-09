import { describe, expect, it, vi } from "vitest";

import { createLearnerApi } from "./learner-api";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

const profile = {
  username: "learner_7",
  leaderboard_opted_in: false,
  revision: 1,
  leaderboard_policy: {
    version: "all_time_practice_xp_v1",
    period: "all_time",
    measure: "confirmed_practice_xp",
    ranking: "competition",
    privacy: "academy_opt_in",
  },
};

describe("community API adapter", () => {
  it.each([
    [409, "username_unavailable"],
    [422, "username_reserved"],
  ])("preserves canonical username rejection %s/%s", async (status, code) => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            type: `https://authorityclosers.com/problems/${String(code).replaceAll("_", "-")}`,
            title: "Community request could not be completed",
            status,
            detail: "Choose another username.",
            instance: "/v1/community/username",
            code,
            request_id: "test-request",
          }),
          {
            status: Number(status),
            headers: { "content-type": "application/problem+json" },
          },
        ),
    );
    await expect(
      createLearnerApi(fetcher).claimUsername("taken_name"),
    ).rejects.toMatchObject({ status, code });
  });

  it("sends only the username claim and no account or tenant selector", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/v1/community/username");
        expect(init?.method).toBe("PUT");
        expect(init?.credentials).toBe("include");
        expect(JSON.parse(String(init?.body))).toEqual({
          username: "Learner_7",
        });
        return response(profile);
      },
    );
    const api = createLearnerApi(fetcher, {
      idempotencyKey: () => "community-claim-1",
    });

    await expect(api.claimUsername("Learner_7")).resolves.toEqual(profile);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("keeps leaderboard participation an explicit revision-guarded mutation", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/v1/community/leaderboard-opt-in");
        expect(init?.method).toBe("PUT");
        expect(JSON.parse(String(init?.body))).toEqual({
          opted_in: true,
          expected_revision: 1,
        });
        return response({
          ...profile,
          leaderboard_opted_in: true,
          revision: 2,
        });
      },
    );
    const api = createLearnerApi(fetcher, {
      idempotencyKey: () => "community-opt-in-1",
    });

    await expect(api.setLeaderboardOptIn(true, 1)).resolves.toMatchObject({
      leaderboard_opted_in: true,
      revision: 2,
    });
  });

  it("reads a stable cursor page without sending identity fields", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(
          "/v1/community/leaderboard?limit=25&cursor=opaque-cursor",
        );
        expect(init?.method).toBeUndefined();
        return response({
          policy: {
            version: "all_time_practice_xp_v1",
            label: "All-time practice XP",
            period: "all_time",
            ranking: "competition",
            scope: "academy",
          },
          items: [
            {
              rank: 1,
              username: "learner_7",
              xp_total: 90,
              is_current_learner: true,
            },
          ],
          next_cursor: null,
        });
      },
    );
    const api = createLearnerApi(fetcher);

    const result = await api.communityLeaderboard(25, "opaque-cursor");

    expect(result.items[0]).toEqual({
      rank: 1,
      username: "learner_7",
      xp_total: 90,
      is_current_learner: true,
    });
    expect(JSON.stringify(result)).not.toContain("email");
  });
});
