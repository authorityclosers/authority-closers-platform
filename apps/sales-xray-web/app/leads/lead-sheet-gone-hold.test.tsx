// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({
  notify: () => undefined,
  dismissNotice: () => undefined,
}));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => ({
    context: { personId: "person-1", tenantId: "tenant-1" },
  }),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { LeadSheet } from "./lead-sheet";
import type { NativeCall } from "./native-phone";
import { callToAnswer, rememberCallToAnswer } from "./pending-answer";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Wise Life, 23 Nov 2026: a seller called a lead, a manager gave it to a
// colleague four minutes later, and the after-call lock kept bringing the
// seller back to a lead they could no longer open, from every screen.
const ACCOUNT = "tenant-1:person-1";
const MOVED = "44444444-4444-4444-8444-444444444444";

const ended = (): NativeCall => ({
  leadId: MOVED,
  number: "+919876543210",
  startedMs: Date.now() - 120_000,
  endedMs: Date.now() - 30_000,
  durationSeconds: 90,
  connected: true,
  result: "answered",
  recording: null,
  final: true,
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  localStorage.clear();
  Element.prototype.scrollIntoView = () => undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ detail: "Not Found" }, { status: 404 })),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}

it("lets go of the after-call lock when the called lead is no longer on the seller's desk", async () => {
  const call = ended();
  expect(rememberCallToAnswer(ACCOUNT, call)).toBe(true);
  expect(callToAnswer(ACCOUNT)?.leadId).toBe(MOVED);

  await act(async () =>
    root.render(
      <LeadSheet
        leadId={MOVED}
        me={null}
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    ),
  );
  await flush();

  expect(document.body.textContent).toContain(
    "This lead isn't on your desk any more",
  );
  expect(callToAnswer(ACCOUNT)).toBeNull();
  // The phone's second report of the same call doesn't lock the seller again.
  expect(rememberCallToAnswer(ACCOUNT, call)).toBe(false);
});
