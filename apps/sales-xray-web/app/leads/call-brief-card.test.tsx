// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { CaptureCall, CaptureState } from "./capture-guard-client";

const guard = vi.hoisted(
  () =>
    new Map<
      string,
      (evidence: {
        native: null;
        server: Partial<CaptureCall> | null;
        unavailable: boolean;
      }) => void
    >(),
);
const reads = vi.hoisted(() => [] as string[]);
vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("./auto-capture-state", () => ({
  watchCapture: (eventId: string, tell: never) => {
    guard.set(eventId, tell);
    return () => guard.delete(eventId);
  },
}));
vi.mock("../acquisition-client", async (original) => ({
  ...(await original<typeof import("../acquisition-client")>()),
  acquisition: async (path: string) => {
    reads.push(path);
    return {
      report: {
        content: {
          structure: {
            overview: { summary: "Asha wants the team plan." },
          },
        },
      },
    };
  },
}));

import { LastCallBrief } from "./call-brief-card";
import type { LeadDetail, LeadEvent } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// QA robot f3525cfb, 09c1fe61, 249f1f8d and 3e459167 (2 Nov 2026): a lead whose
// last call was short asked for its Report on every open, got 404 and logged an
// error. Made-up people and ids only.
const CALL = "22222222-2222-4222-8222-222222222222";
const SUB = "33333333-3333-4333-8333-333333333333";

function detail(event: Partial<LeadEvent>): LeadDetail {
  return {
    lead: { lead_id: "1", stage: "new" },
    events: [{ kind: "call", submission_id: SUB, event_id: CALL, ...event }],
    can_edit: true,
  } as unknown as LeadDetail;
}
function says(state: CaptureState, submission: string | null = SUB) {
  return act(async () =>
    guard.get(CALL)?.({
      native: null,
      server: { event_id: CALL, submission_id: submission, state },
      unavailable: false,
    }),
  );
}

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  guard.clear();
  reads.length = 0;
});
async function render(value: LeadDetail) {
  await act(async () =>
    root.render(<LastCallBrief detail={value} onChanged={() => {}} />),
  );
}

it("never asks for a short call's Report, and shows nothing", async () => {
  await render(detail({}));
  // Until the call's state is known, the panel waits as before.
  expect(host.querySelector('[aria-busy="true"]')).not.toBeNull();
  await says("short_call");
  expect(reads).toEqual([]);
  expect(host.textContent).toBe("");
});

it("reads the Report once the call is Report ready", async () => {
  await render(detail({}));
  await says("analysing");
  expect(reads).toEqual([]);
  await says("report_ready");
  expect(reads).toEqual([`/submissions/${SUB}/report`]);
  expect(host.textContent).toContain("Asha wants the team plan.");
  await says("report_ready");
  expect(reads).toHaveLength(1);
});

it("reads as before a call the guard doesn't follow", async () => {
  await render(detail({}));
  await act(async () =>
    guard.get(CALL)?.({ native: null, server: null, unavailable: true }),
  );
  expect(reads).toEqual([`/submissions/${SUB}/report`]);
});

it("reads as before when the guard has another recording for the call", async () => {
  await render(detail({}));
  await says("waiting", null);
  expect(reads).toEqual([`/submissions/${SUB}/report`]);
});

it("reads straight away a call event with no id (an older answer)", async () => {
  await render(detail({ event_id: null }));
  expect(guard.size).toBe(0);
  expect(reads).toEqual([`/submissions/${SUB}/report`]);
});
