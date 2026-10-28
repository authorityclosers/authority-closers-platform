import { expect, it, vi } from "vitest";
import type { LearnerApi, MeResponse } from "../lib/learner-api";
import { createAccountStore } from "./account-store";

type Avatar = Awaited<ReturnType<LearnerApi["profileAvatar"]>>;
const noAvatar = { avatar: null } as unknown as Avatar;
const me = {
  person_id: "person-test",
  display_name: "Test Learner",
  selected_tenant_id: "workspace-2",
  avatar: null,
} as unknown as MeResponse;
it("shares one me read across mounts/tabs in the app and shows the selected name only for multiple workspaces", async () => {
  const api = {
    me: vi.fn(async () => me),
    profileAvatar: vi.fn(async () => noAvatar),
  };
  const fetcher = vi.fn(async () =>
    Response.json({
      person_id: me.person_id,
      workspaces: [
        { tenant_id: "workspace-1", name: "One" },
        { tenant_id: "workspace-2", name: "Two" },
      ],
    }),
  );
  const store = createAccountStore(api, fetcher as typeof fetch);
  const notify = vi.fn();
  const off = store.subscribe(notify);
  await Promise.all([store.load(), store.load()]);
  off();
  await store.load();
  expect(api.me).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(store.getSnapshot().workspaceName).toBe("Two");
  expect(notify).toHaveBeenCalled();
  expect(store.getSnapshot().me).toBe(me);
});
it.each<{ workspaces: { tenant_id: string; name: string }[] }>([
  { workspaces: [] },
  { workspaces: [{ tenant_id: "workspace-2", name: "Only one" }] },
])(
  "does not invent a workspace for a single or empty membership list",
  async ({ workspaces }) => {
    const store = createAccountStore(
      { me: async () => me, profileAvatar: async () => noAvatar },
      (async () =>
        Response.json({ person_id: me.person_id, workspaces })) as typeof fetch,
    );
    await store.load();
    expect(store.getSnapshot().workspaceName).toBeNull();
  },
);
it("keeps a saved avatar when an older profile read finishes later", async () => {
  let resolve!: (value: Avatar) => void;
  const store = createAccountStore(
    {
      me: async () => me,
      profileAvatar: () =>
        new Promise((r) => {
          resolve = r;
        }),
    },
    (async () => Response.json({})) as typeof fetch,
  );
  const loaded = store.load();
  await Promise.resolve();
  store.updateAvatar("/new-photo");
  // Only the fields the store reads; the rest of the avatar record is irrelevant here.
  resolve({
    avatar: { state: "ready", delivery_url: "/old-photo" },
  } as unknown as Avatar);
  await loaded;
  expect(store.getSnapshot().avatarUrl).toBe("/new-photo");
});
