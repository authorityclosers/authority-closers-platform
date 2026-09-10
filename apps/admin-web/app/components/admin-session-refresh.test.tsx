// @vitest-environment happy-dom
import { act, useEffect, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import {
  ADMIN_SESSION_REFRESH_TIMEOUT_MS,
  AdminSessionProvider,
  useAdminSession,
} from "@ac/operations-web/session";

// Use the actual provider/context; only its session-loading I/O is controlled.
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const account: api.AdminSession = {
  personId: "11111111-1111-4111-8111-111111111111",
  sessionId: "22222222-2222-4222-8222-222222222222",
  tenantId: "33333333-3333-4333-8333-333333333333",
  displayName: "First Coach",
  email: "first@example.test",
  emailVerifiedAt: "2026-09-09T00:00:00Z",
  membershipRole: "learner",
  permissions: [],
  studioCapabilities: [],
};
const otherId = "44444444-4444-4444-8444-444444444444";
let host: HTMLDivElement;
let root: Root;
let mounts: number;
let unmounts: number;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function PrivateForm({ route = "initial" }: { route?: string }) {
  const state = useAdminSession();
  const [draft, setDraft] = useState("Initial value");
  useEffect(() => {
    mounts += 1;
    return () => {
      unmounts += 1;
    };
  }, []);
  if (state.status !== "ready")
    return <p data-session-status="">{state.status}</p>;
  return (
    <form>
      <p data-person="">{state.session.email}</p>
      <p data-route="">{route}</p>
      <input
        aria-label="Private draft"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button type="button" onClick={() => setDraft("Unsaved local draft")}>
        Edit locally
      </button>
    </form>
  );
}

function PrivateModal({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (open) dialog.current?.showModal();
  }, [open]);
  return (
    <dialog
      ref={dialog}
      onClose={() => {
        setOpen(false);
        onClose();
      }}
    >
      <PrivateForm />
    </dialog>
  );
}

async function render(
  refreshKey = "/studio",
  route = "initial",
  revalidateOnFocus = true,
) {
  await act(async () =>
    root.render(
      <AdminSessionProvider
        refreshKey={refreshKey}
        revalidateOnFocus={revalidateOnFocus}
      >
        <PrivateForm route={route} />
      </AdminSessionProvider>,
    ),
  );
}
function subtree() {
  return host.querySelector("[data-private-session-tree]") as HTMLDivElement;
}
function input() {
  return host.querySelector("input") as HTMLInputElement;
}
async function edit() {
  await act(async () =>
    (host.querySelector("form button") as HTMLButtonElement).click(),
  );
}
async function focus() {
  await act(async () => window.dispatchEvent(new Event("focus")));
}
function sessionSignal(call: number) {
  return vi.mocked(api.loadAdminSession).mock.calls[call]?.[1];
}

beforeEach(() => {
  mounts = 0;
  unmounts = 0;
  vi.spyOn(api, "loadAdminSession").mockResolvedValue(account);
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("keeps the default provider compatible and does not opt Admin into focus refresh", async () => {
  const initial = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession).mockReturnValueOnce(initial.promise);
  await act(async () =>
    root.render(
      <AdminSessionProvider>
        <PrivateForm />
      </AdminSessionProvider>,
    ),
  );
  expect(host.textContent).toBe("loading");
  await act(async () => initial.resolve(account));
  await focus();
  expect(api.loadAdminSession).toHaveBeenCalledTimes(1);
  expect(input().value).toBe("Initial value");
});

it("hides and inerts a checking subtree without unmounting or losing its unsaved input", async () => {
  await render();
  await edit();
  const original = input();
  const refresh = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession).mockReturnValueOnce(refresh.promise);
  await focus();
  expect(subtree().hidden).toBe(true);
  expect(subtree().hasAttribute("inert")).toBe(true);
  expect(subtree().getAttribute("aria-hidden")).toBe("true");
  expect(input()).toBe(original);
  expect(unmounts).toBe(0);
  await act(async () => refresh.resolve({ ...account }));
  expect(subtree().hidden).toBe(false);
  expect(subtree().hasAttribute("inert")).toBe(false);
  expect(input()).toBe(original);
  expect(input().value).toBe("Unsaved local draft");
  expect(mounts).toBe(1);
});

it("freezes new route children until the current route session is verified", async () => {
  await render();
  const refresh = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession).mockReturnValueOnce(refresh.promise);
  await render("/studio/settings", "settings");
  expect(subtree().hidden).toBe(true);
  expect(host.querySelector("[data-route]")?.textContent).toBe("initial");
  await act(async () => refresh.resolve(account));
  expect(subtree().hidden).toBe(false);
  expect(host.querySelector("[data-route]")?.textContent).toBe("settings");
});

it.each(["tenantId", "personId", "sessionId"] as const)(
  "resets private children on confirmed %s changes",
  async (field) => {
    await render();
    await edit();
    const original = input();
    vi.mocked(api.loadAdminSession).mockResolvedValueOnce({
      ...account,
      [field]: otherId,
      email: "next@example.test",
    });
    await focus();
    expect(input()).not.toBe(original);
    expect(input().value).toBe("Initial value");
    expect(host.querySelector("[data-person]")?.textContent).toBe(
      "next@example.test",
    );
    expect(unmounts).toBe(1);
  },
);

it("ignores an older route response after a newer session has been verified", async () => {
  await render();
  const old = deferred<api.AdminSession>();
  const current = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession)
    .mockReturnValueOnce(old.promise)
    .mockReturnValueOnce(current.promise);
  await render("/studio/programs", "old route");
  const oldSignal = sessionSignal(1);
  expect(oldSignal?.aborted).toBe(false);
  await render("/studio/settings", "new route");
  expect(oldSignal?.aborted).toBe(true);
  expect(sessionSignal(2)?.aborted).toBe(false);
  await act(async () =>
    current.resolve({
      ...account,
      personId: otherId,
      email: "new@example.test",
    }),
  );
  await act(async () => old.resolve(account));
  expect(host.querySelector("[data-person]")?.textContent).toBe(
    "new@example.test",
  );
  expect(host.querySelector("[data-route]")?.textContent).toBe("new route");
  expect(subtree().hidden).toBe(false);
});

it("coalesces duplicate focus and visible events while a fresh check is pending", async () => {
  await render();
  const refresh = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession).mockReturnValueOnce(refresh.promise);
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("focus"));
  });
  expect(api.loadAdminSession).toHaveBeenCalledTimes(2);
  await act(async () => refresh.resolve(account));
});

it("invalidates checks across hidden-to-visible transitions", async () => {
  await render();
  const old = deferred<api.AdminSession>();
  const current = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession)
    .mockReturnValueOnce(old.promise)
    .mockReturnValueOnce(current.promise);
  await focus();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await act(async () => old.resolve(account));
  expect(subtree().hidden).toBe(true);
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  expect(api.loadAdminSession).toHaveBeenCalledTimes(3);
  await act(async () => current.resolve({ ...account, sessionId: otherId }));
  expect(subtree().hidden).toBe(false);
});

it("does not accept an old in-flight response after focus was lost", async () => {
  await render();
  const old = deferred<api.AdminSession>();
  const current = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession)
    .mockReturnValueOnce(old.promise)
    .mockReturnValueOnce(current.promise);
  await focus();
  await act(async () => window.dispatchEvent(new Event("blur")));
  await focus();
  await act(async () =>
    current.resolve({
      ...account,
      personId: otherId,
      email: "new@example.test",
    }),
  );
  await act(async () => old.resolve(account));
  expect(host.querySelector("[data-person]")?.textContent).toBe(
    "new@example.test",
  );
});

it("keeps failed-refresh input private and restores it after same-identity reconnect", async () => {
  await render();
  await edit();
  const original = input();
  vi.mocked(api.loadAdminSession).mockRejectedValueOnce(
    new TypeError("offline"),
  );
  await focus();
  expect(subtree().hidden).toBe(true);
  expect(input()).toBe(original);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Reconnect",
  );
  await act(async () =>
    (host.querySelector('[role="alert"] button') as HTMLButtonElement).click(),
  );
  expect(subtree().hidden).toBe(false);
  expect(input()).toBe(original);
  expect(input().value).toBe("Unsaved local draft");
});

it("aborts a stalled refresh at the total timeout and recovers the same private input", async () => {
  await render();
  await edit();
  const original = input();
  const stalled = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession).mockReturnValueOnce(stalled.promise);
  vi.useFakeTimers();
  await focus();
  const signal = sessionSignal(1);
  expect(signal?.aborted).toBe(false);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ADMIN_SESSION_REFRESH_TIMEOUT_MS);
  });
  expect(signal?.aborted).toBe(true);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Reconnect",
  );
  expect(input()).toBe(original);
  vi.mocked(api.loadAdminSession).mockResolvedValueOnce(account);
  await act(async () =>
    (host.querySelector('[role="alert"] button') as HTMLButtonElement).click(),
  );
  expect(input()).toBe(original);
  expect(input().value).toBe("Unsaved local draft");
  await act(async () => stalled.resolve({ ...account, sessionId: otherId }));
  expect(input()).toBe(original);
});

it("suspends a native modal without closing its draft and restores it after reconnect", async () => {
  const closed = vi.fn();
  await act(async () =>
    root.render(
      <AdminSessionProvider refreshKey="/studio" revalidateOnFocus>
        <PrivateModal onClose={closed} />
      </AdminSessionProvider>,
    ),
  );
  await edit();
  const dialog = host.querySelector("dialog") as HTMLDialogElement;
  const original = input();
  expect(dialog.open).toBe(true);
  vi.mocked(api.loadAdminSession).mockRejectedValueOnce(
    new TypeError("offline"),
  );
  await focus();
  expect(dialog.open).toBe(false);
  expect(closed).not.toHaveBeenCalled();
  expect(input()).toBe(original);
  await act(async () =>
    (host.querySelector('[role="alert"] button') as HTMLButtonElement).click(),
  );
  expect(dialog.open).toBe(true);
  expect(input()).toBe(original);
  expect(input().value).toBe("Unsaved local draft");
  await act(async () => dialog.close());
  expect(closed).toHaveBeenCalledTimes(1);
});

it("suppresses every queued suspension close across repeated modal checks", async () => {
  const closed = vi.fn();
  await act(async () =>
    root.render(
      <AdminSessionProvider refreshKey="/studio" revalidateOnFocus>
        <PrivateModal onClose={closed} />
      </AdminSessionProvider>,
    ),
  );
  const dialog = host.querySelector("dialog") as HTMLDialogElement;
  // Browsers queue close events; happy-dom normally dispatches synchronously.
  const close = vi
    .spyOn(dialog, "close")
    .mockImplementation(() => dialog.removeAttribute("open"));
  for (let cycle = 0; cycle < 2; cycle += 1) {
    const refresh = deferred<api.AdminSession>();
    vi.mocked(api.loadAdminSession).mockReturnValueOnce(refresh.promise);
    await focus();
    expect(dialog.open).toBe(false);
    await act(async () => refresh.resolve(account));
    expect(dialog.open).toBe(true);
  }
  await act(async () => {
    dialog.dispatchEvent(new Event("close"));
    dialog.dispatchEvent(new Event("close"));
  });
  expect(closed).not.toHaveBeenCalled();
  close.mockRestore();
  await act(async () => dialog.close());
  expect(closed).toHaveBeenCalledTimes(1);
});

it("does not restore an old account's suspended dialog after identity changes", async () => {
  const closed = vi.fn();
  await act(async () =>
    root.render(
      <AdminSessionProvider refreshKey="/studio" revalidateOnFocus>
        <PrivateModal onClose={closed} />
      </AdminSessionProvider>,
    ),
  );
  await edit();
  const oldDialog = host.querySelector("dialog") as HTMLDialogElement;
  const refresh = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession).mockReturnValueOnce(refresh.promise);
  await focus();
  await act(async () => refresh.resolve({ ...account, personId: otherId }));
  expect(oldDialog.isConnected).toBe(false);
  expect(oldDialog.open).toBe(false);
  expect(input().value).toBe("Initial value");
  expect(host.querySelector("dialog")?.open).toBe(true);
  expect(closed).not.toHaveBeenCalled();
});

it("discards stale private children after definitive denial", async () => {
  await render();
  await edit();
  vi.mocked(api.loadAdminSession).mockRejectedValueOnce(
    new api.AdminSessionDenied(),
  );
  await focus();
  expect(input()).toBeNull();
  expect(host.textContent).toBe("denied");
  await render("/studio/settings");
  expect(input().value).toBe("Initial value");
});

it("ignores late results and removes focus listeners after unmount", async () => {
  const initial = deferred<api.AdminSession>();
  vi.mocked(api.loadAdminSession).mockReturnValueOnce(initial.promise);
  await render();
  const signal = sessionSignal(0);
  await act(async () => root.unmount());
  expect(signal?.aborted).toBe(true);
  root = createRoot(host);
  await focus();
  await act(async () => initial.resolve(account));
  expect(host.textContent).toBe("");
  expect(api.loadAdminSession).toHaveBeenCalledTimes(1);
});

it.each(["network", "server"])(
  "shows reconnect for actual session-loader %s failures",
  async (failure) => {
    vi.mocked(api.loadAdminSession).mockRestore();
    vi.stubGlobal(
      "fetch",
      failure === "network"
        ? vi.fn().mockRejectedValue(new TypeError("offline"))
        : vi
            .fn()
            .mockResolvedValue(
              Response.json({ detail: "unavailable" }, { status: 503 }),
            ),
    );
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(
      "Reconnect",
    );
    expect(input()).toBeNull();
  },
);
