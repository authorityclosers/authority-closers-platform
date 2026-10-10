import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Link from "next/link";

import type { Progress } from "./acquisition-client";
import { AcquisitionProcessingPanel } from "./acquisition-processing-panel";
import { WorkspaceAccessProvider } from "./workspace-access";

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
let root: Root;
let host: HTMLDivElement;
let stages: string[];
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  stages = ["C1"];
  fetchMock = vi.fn(async () => {
    const stage = stages.length > 1 ? stages.shift()! : stages[0];
    return Response.json(
      stage === "done"
        ? { state: "completed", current_stage: "C6", report_ready: true }
        : { state: "active", current_stage: stage, report_ready: false },
    );
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function mount(
  props: Partial<Parameters<typeof AcquisitionProcessingPanel>[0]> = {},
  authenticated = true,
) {
  await act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: authenticated ? "ready" : "unauthenticated",
          authenticated,
          context: null,
          retry: () => {},
        }}
      >
        <AcquisitionProcessingPanel
          stageRows={[{ stage: "C2", state: "running" }]}
          statusText="Transcribing your call"
          submissionId={callId}
          progress={running}
          accepted
          fileName="My call.m4a"
          fileMeta="12.4 MB"
          {...props}
        >
          <button type="button">Check status</button>
          <Link href={`/analysis/calls/${callId}`}>This call’s link</Link>
        </AcquisitionProcessingPanel>
      </WorkspaceAccessProvider>,
    ),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

const stepState = (id: string) =>
  host.querySelector(`[data-stage="${id}"]`)?.getAttribute("data-state");
const stepStatus = (id: string) =>
  host.querySelector(`[data-stage="${id}"] small`)?.textContent;
const poll = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(3_000);
  });

it("says one true thing and moves the steps with the plan's live stage", async () => {
  await mount();
  expect(fetchMock.mock.calls[0][0]).toBe(
    `/v1/conversation/acquisition/submissions/${callId}/plan`,
  );
  expect(host.querySelector("h2")?.textContent).toBe("Analysing your call");
  expect(host.textContent).toContain("Usually about 2–4 minutes");
  expect([stepState("C2"), stepState("C4"), stepState("C5")]).toEqual([
    "active",
    "waiting",
    "waiting",
  ]);
  expect(stepStatus("C2")).toBe("In progress");
  expect(stepStatus("C5")).toBe("");
  // None of the old clutter.
  expect(host.textContent).not.toContain("LAST CONFIRMED STATUS");
  expect(host.textContent).not.toContain("Not started");
  expect(host.textContent).not.toContain(
    "confirming that analysis has started",
  );
  expect(host.textContent).not.toMatch(/\b\d+%/);
});

it("marks each step done with the time it took once it is seen to finish", async () => {
  stages = ["C1", "C3", "C3", "C5", "done"];
  await mount();
  await poll();
  expect(stepState("C2")).toBe("done");
  // Listening was already running when the screen opened: no guessed time.
  expect(stepStatus("C2")).toBe("Done");
  expect(stepState("C4")).toBe("active");
  await poll();
  await poll();
  expect(stepStatus("C4")).toBe("Done · 0:06");
  expect(stepState("C5")).toBe("active");
  await poll();
  expect(host.querySelector("h2")?.textContent).toBe("Your report is ready");
  expect(stepStatus("C5")).toBe("Done · 0:03");
  const calls = fetchMock.mock.calls.length;
  await poll();
  expect(fetchMock.mock.calls.length).toBe(calls);
  // If the page hasn't opened the report by itself, offer it.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(8_000);
  });
  expect(
    [...host.querySelectorAll("button")].some(
      (button) => button.textContent === "Open report",
    ),
  ).toBe(true);
});

it("keeps the call's link and other actions in a ⋯ menu while it works", async () => {
  await mount();
  const menu = host.querySelector("details")!;
  expect(menu.querySelector("summary")?.getAttribute("aria-label")).toBe(
    "More actions",
  );
  expect(menu.textContent).toContain("This call’s link");
  expect(menu.textContent).toContain("Check status");
  expect(host.textContent).toContain("My call.m4a");
  expect(host.textContent).toContain("12.4 MB");
  expect(host.textContent).toContain(
    "You can leave this page. Your report will appear in Calls when it’s ready.",
  );
});

it("tells a guest to keep the call's link instead of promising Calls", async () => {
  await mount({}, false);
  expect(host.textContent).toContain(
    "Keep this call’s link to come back while your session and call remain available.",
  );
  expect(host.textContent).not.toContain("appear in Calls");
});

it("pauses calmly: saved work, the reason and the recovery actions in view", async () => {
  stages = ["C3"];
  await mount({
    paused: true,
    stageRows: [
      { stage: "C2", state: "completed" },
      { stage: "C4", state: "uncertain" },
    ],
    progress: {
      ...running,
      state: "held",
      stages: [
        { stage: "C2", state: "completed" },
        { stage: "C4", state: "uncertain" },
      ],
    },
  });
  expect(host.querySelector('[role="status"] h3')?.textContent).toBe(
    "Analysis paused",
  );
  expect(host.textContent).toContain(
    "This stage needs checking before analysis can continue",
  );
  expect(stepState("C4")).toBe("attention");
  expect(stepStatus("C4")).toBe("Paused · needs attention");
  expect(host.textContent).toContain("The completed transcript stays attached");
  expect(host.querySelector("details")).toBeNull();
  expect(
    host.querySelector('[role="group"][aria-label="Call actions"]')
      ?.textContent,
  ).toContain("Check status");
  expect(host.textContent).not.toContain("You can leave this page");
});

it("falls back to the task rows on a server without a plan for the call", async () => {
  fetchMock.mockImplementation(async () =>
    Response.json({ detail: "Not found" }, { status: 404 }),
  );
  await mount({
    stageRows: [
      { stage: "C2", state: "completed" },
      { stage: "C4", state: "running" },
    ],
  });
  expect([stepState("C2"), stepState("C4"), stepState("C5")]).toEqual([
    "done",
    "active",
    "waiting",
  ]);
  const calls = fetchMock.mock.calls.length;
  await poll();
  expect(fetchMock.mock.calls.length).toBe(calls);
});

it("renders a static example with no live claim, read or action", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionProcessingPanel
      staticPreview
      stageRows={[{ stage: "C2", state: "completed" }]}
      statusText="Example"
      fileName="Example call.wav"
    >
      <button type="button">Check status</button>
    </AcquisitionProcessingPanel>,
  );
  expect(markup).toContain("Example processing state");
  expect(markup).toContain("No call was uploaded or analysed");
  expect(markup).not.toContain("Check status");
  expect(markup).not.toContain("You can leave this page");
  expect(fetchMock).not.toHaveBeenCalled();
});
