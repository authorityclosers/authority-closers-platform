// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Progress } from "./acquisition-client";
import { AcquisitionProcessingPanel } from "./acquisition-processing-panel";
import { WorkspaceAccessProvider } from "./workspace-access";

const trackOnce = vi.hoisted(() => vi.fn());
vi.mock("./telemetry", async (original) => ({
  ...(await original<typeof import("./telemetry")>()),
  trackOnce,
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const callId = "0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10";
const running: Progress = {
  state: "active",
  local_state: "completed",
  failure_code: null,
  has_report: false,
  automatic_progression: true,
  stages: [{ stage: "C2", state: "running" }],
};
const done: Progress = { ...running, state: "report_ready", has_report: true };
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  trackOnce.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ state: "active", report_ready: false })),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const render = (progress: Progress) =>
  act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: "ready",
          authenticated: true,
          context: null,
          retry: () => {},
        }}
      >
        <AcquisitionProcessingPanel
          stageRows={[{ stage: "C2", state: "running" }]}
          statusText="Transcribing your call"
          submissionId={callId}
          progress={progress}
          accepted
          fileName="My call.m4a"
          fileMeta="12.4 MB"
        />
      </WorkspaceAccessProvider>,
    ),
  );

it("counts the analysis as seen done when this page watched it finish", async () => {
  await render(running);
  expect(trackOnce).not.toHaveBeenCalled();
  await render(done);
  expect(trackOnce).toHaveBeenCalledWith(
    `analysis-done:${callId}`,
    "sx.analysis_seen_done",
    expect.objectContaining({ wait_band: expect.any(String) }),
  );
});

it("does not count an old call that was already done when it opened", async () => {
  await render(done);
  expect(trackOnce).not.toHaveBeenCalled();
});
