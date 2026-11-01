// @vitest-environment happy-dom
/**
 * Calls never says "No calls yet" before its first answer (robot 48381a47,
 * a9001bc8, 22f8aaea and 79499de5, 1 Nov 2026: on slow answers the empty
 * state showed while calls were on their way, then the page jumped). While the
 * sign-in is still being checked and while a slow list is on its way, the
 * skeleton holds the page; only an answer with no calls shows the empty state.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const address = vi.hoisted(() => ({ search: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => address.search,
  usePathname: () => "/analysis/calls",
}));
vi.mock("./profile-menu", () => ({ ProfileMenu: () => null }));
vi.mock("./capture-setup/recording-check", () => ({
  RecordingLine: () => null,
}));

import { CallsLibrary } from "./calls-library";
import { UploadSessionProvider } from "./hooks/upload-session";
import {
  WorkspaceAccessProvider,
  type WorkspaceAccessValue,
} from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const context = {
  personId: "11111111-1111-4111-8111-111111111111",
  sessionId: "22222222-2222-4222-8222-222222222222",
  tenantId: "33333333-3333-4333-8333-333333333333",
};
const SKELETON = '[aria-label="Loading your calls"]';

let root: Root;
let host: HTMLDivElement;

const access = (
  value: Partial<WorkspaceAccessValue>,
): WorkspaceAccessValue => ({
  status: "ready",
  authenticated: true,
  context,
  retry: () => {},
  ...value,
});

function render(value: WorkspaceAccessValue) {
  root.render(
    <UploadSessionProvider>
      <WorkspaceAccessProvider value={value}>
        <CallsLibrary />
      </WorkspaceAccessProvider>
    </UploadSessionProvider>,
  );
}

async function flush() {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("holds the skeleton until the first answer, never a false No calls yet", async () => {
  const waiting: ((answer: Response) => void)[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo) =>
      String(input).includes("/acquisition/submissions?")
        ? new Promise<Response>((resolve) => waiting.push(resolve))
        : Promise.resolve(new Response("{}", { status: 404 })),
    ),
  );

  // Still finding out who is signed in.
  await act(async () =>
    render(access({ status: "loading", authenticated: null, context: null })),
  );
  expect(host.querySelector(SKELETON)).not.toBeNull();
  expect(host.textContent).not.toContain("No calls yet");

  // Signed in, and the list is slow.
  await act(async () => render(access({})));
  await flush();
  expect(waiting.length).toBeGreaterThan(0);
  expect(host.querySelector(SKELETON)).not.toBeNull();
  expect(host.textContent).not.toContain("No calls yet");

  // The answer has no calls: now, and only now, it says so.
  await act(async () => {
    for (const answer of waiting)
      answer(
        new Response(JSON.stringify({ submissions: [], next_cursor: null }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
  });
  await flush();
  expect(host.querySelector("h2#calls-library-empty")?.textContent).toBe(
    "No calls yet",
  );
  expect(host.querySelector(SKELETON)).toBeNull();
});
