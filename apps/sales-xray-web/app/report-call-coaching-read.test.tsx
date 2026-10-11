import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReportCallCoaching } from "./report-call-coaching";
import {
  callCoachingBinding as binding,
  fictionalCallCoaching,
} from "./report-call-coaching.fixture";
import { parseCallCoaching } from "./report-call-coaching-client";
import { fictionalClip } from "./coaching/coaching.fixture";
import { clipSource } from "./coaching/media-contract";
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
  vi.restoreAllMocks();
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
  const callLink = container.querySelector<HTMLAnchorElement>(
    `a[href="/coaching?call=${submissionId}"]`,
  );
  expect(callLink?.textContent).toBe("Open full coaching for this call");
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
it("offers 'With context' when the Report can play the lines around a moment", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(fictionalCallCoaching()))),
  );
  const contextual = vi.fn();
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={access}>
        <ReportCallCoaching
          callId={submissionId}
          data={data}
          onSelectEvidence={vi.fn()}
          onSelectContextualPlayback={contextual}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  const button = [...container.querySelectorAll("button")].find(
    (b) => b.textContent === "With context",
  )!;
  expect(button).toBeTruthy();
  await act(async () => button.click());
  expect(contextual).toHaveBeenCalledOnce();
  expect(contextual.mock.calls[0][1]).toBe("Coaching for this call");
});
it("uses a source-checked server bootstrap without another read", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await render(access, true);
  expect(container.textContent).toContain("Fictional API focus");
  expect(fetcher).not.toHaveBeenCalled();
  expect(
    container.querySelector(`a[href="/coaching?call=${submissionId}"]`),
  ).not.toBeNull();
});
it("renders reviewed examples from the call read without eager audio and keeps the lesson on media failure", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          ...fictionalCallCoaching(),
          media_clips: [fictionalClip],
        }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  await render();
  expect(container.textContent).toContain("Read by a stand-in voice");
  expect(container.querySelector("audio")).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
  const button = (label: string) =>
    [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (item) => item.textContent === label,
    )!;
  await act(async () => button("Next slide").click());
  expect(container.textContent).toContain("Wait for their answer.");
  await act(async () => button("Play coaching clip").click());
  const audio = container.querySelector("audio")!;
  expect(audio.getAttribute("src")).toBe(clipSource(fictionalClip));
  expect(play).not.toHaveBeenCalled();
  await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
  expect(audio.currentTime).toBe(fictionalClip.start_ms / 1000);
  expect(play).toHaveBeenCalledOnce();
  await act(async () => audio.dispatchEvent(new Event("error")));
  expect(container.textContent).toContain("Narration is unavailable");
  expect(container.textContent).toContain("Your next-call mission");
  expect(container.textContent).toContain(fictionalClip.transcript_excerpt);
  await act(async () => button("Try clip again").click());
  expect(container.querySelector("audio")).not.toBe(audio);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("removes active media immediately when the workspace changes", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...fictionalCallCoaching(),
          media_clips: [fictionalClip],
        }),
      ),
    )
    .mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  await render();
  await act(async () =>
    [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((item) => item.textContent === "Play coaching clip")!
      .click(),
  );
  expect(container.querySelector("audio")).not.toBeNull();
  await render({
    ...access,
    context: {
      ...access.context!,
      tenantId: "00000000-0000-0000-0000-000000000009",
    },
  });
  expect(container.querySelector("audio")).toBeNull();
  expect(container.textContent).not.toContain(fictionalClip.title);
  expect(container.textContent).not.toContain(fictionalClip.transcript_excerpt);
});
it.each([true, false])(
  "resets playback on a changed Coaching digest even with an acquisition pin of %s",
  async (pinned) => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const view = (revision: string) => (
      <WorkspaceAccessContext.Provider value={access}>
        <ReportCallCoaching
          callId={submissionId}
          data={{
            ...data,
            reportRevision: pinned ? revision : undefined,
            callCoaching: parseCallCoaching(
              {
                ...fictionalCallCoaching(),
                report_revision: revision,
                media_clips: [fictionalClip],
              },
              { ...binding, reportRevision: pinned ? revision : undefined },
            ),
          }}
        />
      </WorkspaceAccessContext.Provider>
    );
    await act(async () => root.render(view("b".repeat(64))));
    await act(async () =>
      [...container.querySelectorAll<HTMLButtonElement>("button")]
        .find((item) => item.textContent === "Play coaching clip")!
        .click(),
    );
    const audio = container.querySelector("audio")!;
    expect(audio).not.toBeNull();
    await act(async () => root.render(view("c".repeat(64))));
    expect(audio.isConnected).toBe(false);
    expect(container.querySelector("audio")).toBeNull();
    expect(container.textContent).toContain(fictionalClip.title);
    expect(fetcher).not.toHaveBeenCalled();
  },
);
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
