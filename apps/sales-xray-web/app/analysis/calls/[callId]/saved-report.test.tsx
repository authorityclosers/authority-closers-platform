import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { ScopedSavedReport } from "../../../report-preload";
import { WorkspaceAccessContext } from "../../../workspace-access";

const bridge = vi.hoisted(() => {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { gate, release, requests: [] as ((value: unknown) => void)[] };
});
vi.mock("../../../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("../../../notice-center", () => ({ notify: vi.fn() }));
vi.mock("../../../report-preload", () => ({
  preloadSavedReport: () =>
    new Promise((resolve) => {
      bridge.requests.push(resolve);
    }),
}));
vi.mock("../../../acquisition-studio", async () => {
  await bridge.gate;
  return {
    AcquisitionStudio: ({
      initialSavedReport,
    }: {
      initialSavedReport?: ScopedSavedReport;
    }) => (
      <div data-full-report data-identity={initialSavedReport?.identityKey}>
        {initialSavedReport?.value.result.report.summary}
      </div>
    ),
  };
});

import { SavedReportPage } from "./saved-report";
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("shows the verified summary before the details bundle, and drops it immediately on a workspace change", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const show = (tenantId: string) =>
    act(async () =>
      root.render(
        <WorkspaceAccessContext.Provider
          value={{
            status: "ready",
            authenticated: true,
            context: {
              personId: "fictional-person",
              sessionId: "fictional-session",
              tenantId,
            },
            retry: () => {},
          }}
        >
          <SavedReportPage callId="fictional-call" />
        </WorkspaceAccessContext.Provider>,
      ),
    );
  const ready = (summary: string) => ({
    state: "ready",
    submission: { id: "fictional-call" },
    progress: {},
    result: { report: { summary } },
  });
  try {
    await show("fictional-workspace-a");
    await act(async () => bridge.requests[0](ready("First fictional summary")));
    expect(
      host.querySelector("[data-report-summary-preview]")?.textContent,
    ).toBe("First fictional summary");
    expect(host.querySelector("[data-full-report]")).toBeNull();
    await show("fictional-workspace-b");
    expect(host.textContent).not.toContain("First fictional summary");
    await act(async () =>
      bridge.requests[1](ready("Second fictional summary")),
    );
    await act(async () => {
      bridge.release();
      await bridge.gate;
      await vi.dynamicImportSettled();
    });
    expect(host.querySelector("[data-full-report]")?.textContent).toBe(
      "Second fictional summary",
    );
    expect(
      host.querySelector("[data-full-report]")?.getAttribute("data-identity"),
    ).toBe(
      JSON.stringify([
        "fictional-person",
        "fictional-session",
        "fictional-workspace-b",
      ]),
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
