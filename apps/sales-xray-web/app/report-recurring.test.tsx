import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { ReportModes } from "./report-modes";
import {
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";

const { recurringIssue } = vi.hoisted(() => ({ recurringIssue: vi.fn() }));
vi.mock("./coaching/recurring-issue", () => ({ recurringIssue }));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CALL = "00000000-0000-4000-8000-000000000077";
const access: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: { personId: "person-1", tenantId: "tenant-1", sessionId: "s-1" },
  retry: () => {},
};

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
  recurringIssue.mockReset();
});

async function mount() {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <ReportModes
          structure="pillars"
          initialView="story"
          panels={[]}
          boundCallId={CALL}
          documentData={{ report: amitReport, transcript: amitTranscript }}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  cleanup = () => {
    act(() => root.unmount());
    host.remove();
  };
  return host.querySelector<HTMLElement>('[data-report-pillar="moments"]')!;
}

it("says once, under What Didn't, when Coaching sees the issue recurring", async () => {
  recurringIssue.mockResolvedValue({ recurring: true, href: "/coaching" });
  const pillar = await mount();
  expect(recurringIssue).toHaveBeenCalledWith(
    CALL,
    { personId: "person-1", tenantId: "tenant-1", sessionId: "s-1" },
    expect.any(AbortSignal),
  );
  expect(pillar.textContent).toContain(
    "This issue may be part of a recurring pattern",
  );
  expect(pillar.querySelector('a[href="/coaching"]')).not.toBeNull();
});

it("shows nothing when it doesn't recur or Coaching can't say", async () => {
  recurringIssue.mockResolvedValue({ recurring: false, href: "/coaching" });
  expect((await mount()).textContent).not.toContain("recurring pattern");
  cleanup?.();
  cleanup = null;
  recurringIssue.mockResolvedValue(null);
  expect((await mount()).textContent).not.toContain("recurring pattern");
});
