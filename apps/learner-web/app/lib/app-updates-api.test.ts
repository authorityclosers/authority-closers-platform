import { describe, expect, it, vi } from "vitest";
import { createAppUpdatesApi, appUpdatesSchema } from "./app-updates-api";
import { createLearnerApi } from "./learner-api";

export const updateFeedFixture = {
  person_id: "9b678390-0d63-450c-9257-e6078c3b030e",
  tenant_id: "c94b31ee-27fd-4b70-9525-2d176437ba42",
  items: [
    {
      id: "app-updates-v0-2-alpha",
      title: "A home for app updates",
      message: "See what changed in your app.",
      version: "v0.2 Alpha",
      highlights: ["Version notes", "Feature links", "Saved read state"],
      target_href: "/notifications",
      created_at: "2026-09-10T00:00:00Z",
      read: false,
    },
  ],
  unread_count: 1,
};

describe("app update API", () => {
  it("loads only the signed-in account and saves without account selectors or offline state", async () => {
    const fetcher = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify(updateFeedFixture), {
          headers: { "Content-Type": "application/json" },
        }),
    );
    const api = createAppUpdatesApi(createLearnerApi(fetcher));
    const signal = new AbortController().signal;
    expect(await api.list(signal)).toEqual(updateFeedFixture);
    fetcher.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...updateFeedFixture,
          unread_count: 0,
          items: updateFeedFixture.items.map((item) => ({
            ...item,
            read: true,
          })),
        }),
      ),
    );
    await api.markRead("app-updates-v0-2-alpha", signal);
    expect(fetcher.mock.calls[0]).toEqual([
      "/v1/me/app-updates",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        credentials: "include",
        signal,
      }),
    ]);
    expect(fetcher.mock.calls[1]).toEqual([
      "/v1/me/app-updates/app-updates-v0-2-alpha/read",
      expect.objectContaining({
        method: "POST",
        mode: "same-origin",
        redirect: "error",
        cache: "no-store",
      }),
    ]);
    expect(fetcher.mock.calls[1][1]).not.toHaveProperty("body");
  });
  it("rejects path traversal before issuing a request", async () => {
    const fetcher = vi.fn();
    const api = createAppUpdatesApi(createLearnerApi(fetcher));
    await expect(
      api.markRead("../other-account", new AbortController().signal),
    ).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("requires the requested receipt to be confirmed in a successful save response", async () => {
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify(updateFeedFixture)),
    );
    await expect(
      createAppUpdatesApi(createLearnerApi(fetcher)).markRead(
        "app-updates-v0-2-alpha",
        new AbortController().signal,
      ),
    ).rejects.toThrow("did not confirm");
  });
  it("rejects invented unread counts, duplicate entries and malformed IDs", () => {
    expect(
      appUpdatesSchema.safeParse({ ...updateFeedFixture, unread_count: 3 })
        .success,
    ).toBe(false);
    expect(
      appUpdatesSchema.safeParse({
        ...updateFeedFixture,
        items: [...updateFeedFixture.items, ...updateFeedFixture.items],
        unread_count: 2,
      }).success,
    ).toBe(false);
    expect(
      appUpdatesSchema.safeParse({ ...updateFeedFixture, person_id: "someone" })
        .success,
    ).toBe(false);
  });
});
