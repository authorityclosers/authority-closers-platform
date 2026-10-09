import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";
import { createUpdatesStore, useShellUpdates } from "./updates-store";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const note = {
  key: "seed-fictional",
  version: 1,
  release_id: "fictional",
  date: "2026-10-05",
  title: "Fictional update",
  items: ["A fictional improvement"],
  major: true,
  draft: false,
  seen: false,
  published_at: null,
};
const release = {
  id: "updates:fictional",
  kind: "updates",
  count: 1,
  title: "1 new update",
  href: null,
  urgent: false,
  created_at: "2026-10-05T12:00:00Z",
  read: false,
};
function responses() {
  let seen = false;
  return vi.fn().mockImplementation((path: string) => {
    if (path.endsWith("/seen") || path.endsWith("/read")) seen = true;
    return Promise.resolve(
      Response.json(
        path === "/v1/updates"
          ? { updates: [{ ...note, seen }], unseen_count: seen ? 0 : 1 }
          : path === "/v1/notifications"
            ? {
                notifications: [{ ...release, read: seen }],
                unread_count: seen ? 0 : 1,
              }
            : path.endsWith("/seen")
              ? { unseen_count: 0 }
              : { unread_count: 0 },
      ),
    );
  });
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("shares concurrent refreshes and clears the badge from a successful account receipt", async () => {
  const fetcher = responses();
  vi.stubGlobal("fetch", fetcher);
  const store = createUpdatesStore();
  const first = store.refresh();
  expect(store.refresh()).toBe(first);
  await first;
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(store.getSnapshot().unseen_count).toBe(1);
  await store.markSeen([note.key]);
  expect(store.getSnapshot()).toMatchObject({
    unseen_count: 0,
    unread_count: 0,
    notes: [{ seen: true }],
    notifications: [{ read: true }],
  });
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/updates/seen",
    expect.objectContaining({ body: JSON.stringify({ keys: [note.key] }) }),
  );
});
it("refreshes both lists when a release notification is marked read", async () => {
  const fetcher = responses();
  vi.stubGlobal("fetch", fetcher);
  const store = createUpdatesStore();
  await store.refresh();
  await store.markRead([release.id]);
  expect(store.getSnapshot()).toMatchObject({
    unseen_count: 0,
    unread_count: 0,
    notes: [{ seen: true }],
  });
});
it("keeps the last lists and counts when a refresh or acknowledgement fails", async () => {
  const fetcher = responses();
  vi.stubGlobal("fetch", fetcher);
  const store = createUpdatesStore();
  await store.refresh();
  const previous = store.getSnapshot();
  fetcher.mockImplementation(() =>
    Promise.resolve(new Response(null, { status: 503 })),
  );
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({
    notes: previous.notes,
    notifications: previous.notifications,
    unseen_count: 1,
    unread_count: 1,
    status: "error",
  });
  await expect(store.markSeen([note.key])).rejects.toThrow("503");
  expect(store.getSnapshot().unseen_count).toBe(1);
});
it("shows What's new on first load even when the notifications payload is malformed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((path: string) =>
      Promise.resolve(
        Response.json(
          path === "/v1/updates"
            ? { updates: [note], unseen_count: 1 }
            : {
                notifications: [{ ...release, count: "invalid" }],
                unread_count: 1,
              },
        ),
      ),
    ),
  );
  const store = createUpdatesStore();
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({
    notes: [note],
    unseen_count: 1,
    status: "ready",
    notifications: [],
    notifications_status: "error",
  });
});
it("shows the bell on first load even when What's new fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation((path: string) =>
        Promise.resolve(
          path === "/v1/updates"
            ? new Response(null, { status: 503 })
            : Response.json({ notifications: [release], unread_count: 1 }),
        ),
      ),
  );
  const store = createUpdatesStore();
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({
    notes: [],
    status: "error",
    notifications: [release],
    unread_count: 1,
    notifications_status: "ready",
  });
});
it("publishes each surface before the other pending request finishes", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((path: string) =>
      path === "/v1/notifications"
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(Response.json({ updates: [note], unseen_count: 1 })),
    ),
  );
  const store = createUpdatesStore();
  const first = store.refresh();
  await vi.waitFor(() => expect(store.getSnapshot().status).toBe("ready"));
  expect(store.getSnapshot().notifications_status).toBe("loading");
  expect(store.refresh()).toBe(first);
  finish(Response.json({ notifications: [release], unread_count: 1 }));
  await first;
  expect(store.getSnapshot().notifications_status).toBe("ready");
});
it("keeps only the failed surface's last list while updating the healthy one", async () => {
  const fetcher = responses();
  vi.stubGlobal("fetch", fetcher);
  const store = createUpdatesStore();
  await store.refresh();
  fetcher.mockImplementation((path: string) =>
    Promise.resolve(
      path === "/v1/notifications"
        ? new Response(null, { status: 503 })
        : Response.json({
            updates: [{ ...note, title: "New fictional title" }],
            unseen_count: 1,
          }),
    ),
  );
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({
    notes: [{ title: "New fictional title" }],
    status: "ready",
    notifications: [release],
    unread_count: 1,
    notifications_status: "error",
  });
  fetcher.mockImplementation((path: string) =>
    Promise.resolve(
      path === "/v1/updates"
        ? new Response(null, { status: 503 })
        : Response.json({ notifications: [], unread_count: 0 }),
    ),
  );
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({
    notes: [{ title: "New fictional title" }],
    unseen_count: 1,
    status: "error",
    notifications: [],
    unread_count: 0,
    notifications_status: "ready",
  });
});
it("ignores a stale read that arrives after a newer seen receipt", async () => {
  const fetcher = responses();
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const store = createUpdatesStore();
  const stale = store.refresh();
  await store.markSeen([note.key]);
  resolve(Response.json({ updates: [note], unseen_count: 1 }));
  await stale;
  expect(store.getSnapshot()).toMatchObject({
    unseen_count: 0,
    notes: [{ seen: true }],
  });
});
it("does not dispatch queued acknowledgements after the account/session changes", async () => {
  let current = true;
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const store = createUpdatesStore(() => current);
  const first = store.markSeen([note.key]);
  const queued = store.markRead([release.id]);
  const rejected = expect(queued).rejects.toThrow("updates_session_changed");
  await Promise.resolve();
  current = false;
  resolve(Response.json({ unseen_count: 0 }));
  await first;
  await rejected;
  expect(fetcher).toHaveBeenCalledOnce();
});
it("refreshes on focus and every five minutes, and hides another account's cached list", async () => {
  vi.useFakeTimers();
  const fetcher = responses();
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const access: WorkspaceAccessValue = {
    status: "ready",
    authenticated: true,
    context: { personId: "fictional-hook", sessionId: "s", tenantId: "t" },
    retry: () => {},
  };
  function Viewer() {
    const updates = useShellUpdates();
    return <span>{updates.notes[0]?.title ?? "empty"}</span>;
  }
  const render = (value: WorkspaceAccessValue) =>
    root.render(
      <WorkspaceAccessContext.Provider value={value}>
        <Viewer />
      </WorkspaceAccessContext.Provider>,
    );
  try {
    await act(async () => render(access));
    expect(host.textContent).toBe(note.title);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(fetcher).toHaveBeenCalledTimes(4);
    await act(async () => vi.advanceTimersByTime(5 * 60 * 1000));
    expect(fetcher).toHaveBeenCalledTimes(6);
    fetcher.mockImplementation(() =>
      Promise.resolve(new Response(null, { status: 503 })),
    );
    await act(async () =>
      render({
        ...access,
        context: { ...access.context!, personId: "fictional-other" },
      }),
    );
    expect(host.textContent).toBe("empty");
    await act(async () =>
      render({ ...access, authenticated: false, context: null }),
    );
    const calls = fetcher.mock.calls.length;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      vi.advanceTimersByTime(5 * 60 * 1000);
    });
    expect(fetcher).toHaveBeenCalledTimes(calls);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
