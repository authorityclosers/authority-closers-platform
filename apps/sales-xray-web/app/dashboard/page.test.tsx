// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessContext } from "../workspace-access";
import DashboardPage from "./page";

// Exercise the real dashboard reads without the shell's separate profile reads.
vi.mock("../shell/lightbox-shell", () => ({
  LightboxShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
const signIn = vi.fn();
const base = "/v1/conversation/acquisition";

async function renderPage(authenticated: boolean) {
  await act(async () => {
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: authenticated ? "ready" : "unauthenticated",
          authenticated,
          context: authenticated
            ? {
                personId: "person-1",
                sessionId: "session-1",
                tenantId: "tenant-1",
              }
            : null,
          retry: () => {},
          requestAccountSignIn: signIn,
        }}
      >
        <DashboardPage />
      </WorkspaceAccessContext.Provider>,
    );
  });
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  signIn.mockClear();
  fetchMock = vi
    .fn()
    .mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 }),
    );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("skips all dashboard reads for guests and uses the existing sign-in action", async () => {
  await renderPage(false);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Sign in to see your dashboard");
  expect(host.textContent).not.toContain("Couldn't load");
  const link = host.querySelector<HTMLAnchorElement>('a[href="/login"]')!;
  expect(link.textContent).toBe("Sign in");
  await act(async () => link.click());
  expect(signIn).toHaveBeenCalledOnce();
});

it("starts the four account reads after sign-in and preserves missing-route errors", async () => {
  await renderPage(false);
  await renderPage(true);
  expect(fetchMock.mock.calls.map(([path]) => path).sort()).toEqual(
    ["/submissions/summary", "/activity", "/session", "/submissions"]
      .map((path) => base + path)
      .sort(),
  );
  expect(host.textContent).not.toContain("Sign in to see your dashboard");
  // Summary/activity keep their existing unavailable state; session/recents
  // keep their errors. A missing API must not become invented empty data.
  expect(host.textContent).toContain("Not available yet");
  expect(host.textContent?.match(/Couldn't load/g)).toHaveLength(2);
});

it("aborts pending reads and removes the cards when the session signs out", async () => {
  fetchMock.mockImplementation(() => new Promise(() => {}));
  await renderPage(true);
  const signals = fetchMock.mock.calls.map(
    ([, init]) => init.signal as AbortSignal,
  );
  expect(signals).toHaveLength(4);
  expect(signals.every((signal) => !signal.aborted)).toBe(true);
  await renderPage(false);
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  expect(host.textContent).toContain("Sign in to see your dashboard");
  expect(host.textContent).not.toContain("Calls analysed");
  expect(fetchMock).toHaveBeenCalledTimes(4);
});
