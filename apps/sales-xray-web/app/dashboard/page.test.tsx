// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessContext } from "../workspace-access";
import DashboardPage from "./route-view";

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
  const policyLinks = host.querySelectorAll<HTMLAnchorElement>(
    'nav[aria-label="Sales Xray policy pages"] a',
  );
  expect([...policyLinks].map((link) => link.getAttribute("href"))).toEqual([
    "/pricing",
    "/terms",
    "/privacy",
    "/refunds",
    "/delivery",
    "/contact",
  ]);
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
  // Failed reads keep their skeletons and raise one corner card that retries.
  expect(host.textContent).not.toContain("Couldn't load");
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Some dashboard numbers could not load",
  );
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

it("explains a workspace without Sales Xray access instead of failing each card", async () => {
  fetchMock.mockImplementation(
    async () =>
      new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403 }),
  );
  await renderPage(true);
  expect(host.textContent).toContain(
    "Sales Xray isn't on for this workspace yet",
  );
  expect(host.textContent).not.toContain("Couldn't load");
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(
    [...host.querySelectorAll("button")].some(
      (button) => button.textContent === "Switch account",
    ),
  ).toBe(true);
});

it("renders both the ring and used-minutes text for finite allowances", async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/session")) {
      return new Response(
        JSON.stringify({
          allowance: {
            allowance_seconds: 6000,
            committed_seconds: 1800,
            available_seconds: 4200,
            unlimited: false,
          },
        }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify({ detail: "Not Found" }), {
      status: 404,
    });
  });

  await renderPage(true);

  expect(host.textContent).toContain("70 min");
  expect(host.textContent).toContain("left of 100 min");
  const usedElement = host.querySelector('[title="30 of 100 min used"]');
  expect(usedElement).not.toBeNull();
  expect(usedElement?.textContent).toContain("30");
  expect(usedElement?.textContent).toContain("min used");
  const gaugeSvg = host.querySelector("svg");
  expect(gaugeSvg).not.toBeNull();
});

it("renders unlimited allowances with clock icon and without used-minutes text", async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/session")) {
      return new Response(
        JSON.stringify({
          allowance: {
            allowance_seconds: 0,
            committed_seconds: 0,
            available_seconds: 0,
            unlimited: true,
          },
        }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify({ detail: "Not Found" }), {
      status: 404,
    });
  });

  await renderPage(true);

  expect(host.textContent).toContain("Unlimited");
  expect(host.textContent).toContain("Analysis time");
  expect(host.querySelector('[title*="min used"]')).toBeNull();
  expect(host.textContent).not.toContain("min used");
});
