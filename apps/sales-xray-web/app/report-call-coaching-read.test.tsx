import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReportCallCoaching } from "./report-call-coaching";
import {
  callCoachingBinding as binding,
  fictionalCallCoaching,
} from "./report-call-coaching.fixture";
import { parseCallCoaching } from "./report-call-coaching-client";
import { parseAcquisitionReport } from "./report-contract";
import {
  envelope,
  recordingId,
  submissionId,
  transcript,
} from "../tests/acquisition-fixture";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";

const notices = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("./notice-center", () => notices);
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const access: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: {
    personId: binding.personId,
    tenantId: binding.tenantId,
    sessionId: binding.sessionId!,
  },
  retry: vi.fn(),
};
const report = parseAcquisitionReport(
  envelope,
  { submissionId, recordingId },
  transcript,
).report;
const data = { report, transcript, recordingId };
let container: HTMLDivElement, root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  notices.notify.mockClear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});
async function render(context = access, bootstrap = false, selected = vi.fn()) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={context}>
        <ReportCallCoaching
          callId={submissionId}
          data={
            bootstrap
              ? {
                  ...data,
                  callCoaching: parseCallCoaching(
                    fictionalCallCoaching(),
                    binding,
                  ),
                }
              : data
          }
          onSelectEvidence={selected}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
}

it("renders current-call API coaching and its exact source, not across-call state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(fictionalCallCoaching()))),
  );
  const selected = vi.fn();
  await render(access, false, selected);
  expect(container.textContent).toContain("Fictional API focus");
  expect(container.querySelector('[data-state="ready"]')).not.toBeNull();
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>("[data-call-coaching] button")!
      .click(),
  );
  expect(selected.mock.calls[0][0].segment_id).toBe(transcript.segments[0].id);
  expect(container.textContent).not.toContain(
    "Compare the situations in two calls",
  );
});
it("uses a source-checked server bootstrap without another read", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await render(access, true);
  expect(container.textContent).toContain("Fictional API focus");
  expect(fetcher).not.toHaveBeenCalled();
});
it("does not reuse a bootstrap from the previous session of the same person", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
  await render(access, true);
  expect(container.textContent).toContain("Fictional API focus");
  await render(
    {
      ...access,
      context: {
        ...access.context!,
        sessionId: "00000000-0000-0000-0000-000000000009",
      },
    },
    true,
  );
  expect(container.textContent).not.toContain("Fictional API focus");
  expect(container.textContent).not.toContain(transcript.segments[0].text);
});
it("keeps the report focus available if this API has not deployed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("private error", { status: 404 })),
  );
  await render();
  expect(container.querySelector('[data-state="report-focus"]')).not.toBeNull();
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({ title: "Call coaching unavailable" }),
  );
  expect(container.textContent).not.toContain("private error");
});
it.each([401, 403])(
  "withholds coaching quotes when current account admission returns %s",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("private error", { status })),
    );
    await render();
    expect(
      container.querySelector('[data-state="unavailable"]'),
    ).not.toBeNull();
    expect(container.textContent).not.toContain(transcript.segments[0].text);
    expect(container.querySelector('[data-state="report-focus"]')).toBeNull();
  },
);
it("withholds a call removed after an authorised coaching read", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(fictionalCallCoaching())),
    )
    .mockResolvedValueOnce(new Response("private error", { status: 404 }));
  vi.stubGlobal("fetch", fetcher);
  await render();
  expect(container.textContent).toContain("Fictional API focus");
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <ReportCallCoaching
          callId={submissionId}
          data={{ ...data, report: { ...report } }}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  expect(container.querySelector('[data-state="unavailable"]')).not.toBeNull();
  expect(container.textContent).not.toContain(transcript.segments[0].text);
  expect(container.querySelector('[data-state="report-focus"]')).toBeNull();
});
it("withholds old private coaching immediately on workspace/session changes", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(fictionalCallCoaching())),
    )
    .mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  await render();
  expect(container.textContent).toContain("Fictional API focus");
  await render({
    ...access,
    context: {
      ...access.context!,
      tenantId: "00000000-0000-0000-0000-000000000009",
    },
  });
  expect(container.textContent).not.toContain("Fictional API focus");
  expect(container.textContent).not.toContain(transcript.segments[0].text);
  expect(container.querySelector("button")).toBeNull();
});
it("does not restore old report quotes after canonical withholding and a failed retry", async () => {
  const unavailable = {
    ...fictionalCallCoaching(),
    state: "unavailable",
    basis: "unavailable",
    focus: null,
    evidence: [],
    lesson: null,
    practice: null,
    mission: null,
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(unavailable)))
    .mockResolvedValueOnce(new Response("private error", { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  await render();
  expect(container.querySelector('[data-state="unavailable"]')).not.toBeNull();
  await act(async () =>
    container.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(container.querySelector('[data-state="unavailable"]')).not.toBeNull();
  expect(container.textContent).not.toContain(transcript.segments[0].text);
});
