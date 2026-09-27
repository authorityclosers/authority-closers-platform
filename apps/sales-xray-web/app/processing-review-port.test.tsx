import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  localReviewFrameId,
  parseLocalReviewObservation,
  reviewFrameId,
  useProcessingReview,
} from "./processing-review-port.dev";
import { useProcessingReview as productionPort } from "./processing-review-port";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const call = "11111111-1111-4111-8111-111111111111",
  frame = "33333333-3333-4333-8333-333333333333",
  localFrame = "55555555-5555-4555-8555-555555555555";
let root: Root, container: HTMLDivElement;
const hash = `#sx-review=v1&mode=observed&frame=${frame}`;
const receipt = () => ({
  submission_id: call,
  recording_id: "22222222-2222-4222-8222-222222222222",
  source_sha256: "a".repeat(64),
  state: "active",
  local_state: "completed",
  has_report: false,
  automatic_progression: true,
  stages: [{ stage: "C2", state: "running" }],
});
const body = () => ({
  receipt: receipt(),
  observedAt: Date.now() - 1000,
  leaseUntil: Date.now() + 30_000,
});
const localBody = () => ({
  id: localFrame,
  sequence: 2,
  observedAt: Date.now() - 1000,
  expiresAt: Date.now() + 60_000,
  state: "upload.file.selected",
  label:
    "Upload · selected file · Sales call.wav · 0.2 MB · privacy details open · consent checkbox unchecked · report language hi-Deva+en · account or guest session present",
  observation: {
    phase: "upload.file.selected",
    privacy_open: true,
    consent_checked: false,
    report_language: "hi-Deva+en",
    verification: "session-present",
    file_name: "Sales call.wav",
    file_size_bytes: 180000,
  },
});
const mockFetch = (
  extra: (path: string, init?: RequestInit) => unknown = () => body(),
) =>
  vi.fn(async (path: string, init: RequestInit = {}) => {
    if (path === "/health")
      return { ok: true, json: async () => ({ analysis_read_only: true }) };
    return extra(path, init);
  });
function View() {
  const review = useProcessingReview(call);
  return (
    <p>
      {review.frame
        ? review.frame.progress.stages[0].state
        : review.localFrame
          ? review.localFrame.label
          : review.message || "live"}
    </p>
  );
}
function CaptureView() {
  const { captureLocal, readOnly, localFrame } = useProcessingReview(call);
  useEffect(() => {
    captureLocal({
      phase: "upload.empty",
      privacy_open: false,
      consent_checked: false,
      report_language: null,
      verification: "checking",
      file_name: null,
      file_size_bytes: null,
    });
  }, [captureLocal]);
  return (
    <p>{localFrame?.label || (readOnly === true ? "read-only" : "waiting")}</p>
  );
}
beforeEach(() => {
  vi.useFakeTimers();
  window.history.replaceState(null, "", `/?call=${call}${hash}`);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});
it("production ignores inspection selectors and makes no review requests", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  expect(productionPort(call)).toEqual({
    requested: false,
    frame: null,
    localRequested: false,
    localFrame: null,
    fixtureRequested: false,
    fixtureFrame: null,
    readOnly: false,
    captureLocal: expect.any(Function),
    message: "",
  });
  expect(fetch).not.toHaveBeenCalled();
});
it("opens only local fixture data after read-only health is confirmed", async () => {
  window.history.replaceState(null, "", "/?new=1&sx-fixture=processing.paused");
  const fetch = mockFetch(() => {
    throw new Error("Fixture inspection must not call any other endpoint");
  });
  vi.stubGlobal("fetch", fetch);
  function FixtureView() {
    const selected = useProcessingReview(null);
    return (
      <p
        data-requested={String(selected.fixtureRequested)}
        data-progress={selected.fixtureFrame?.progress?.state ?? ""}
      >
        {selected.fixtureFrame?.label ?? selected.message}
      </p>
    );
  }
  await act(async () => root.render(<FixtureView />));
  expect(container.textContent).toBe("Analysis paused");
  expect(container.querySelector("p")?.dataset.requested).toBe("true");
  expect(container.querySelector("p")?.dataset.progress).toBe("held");
  expect(fetch.mock.calls.map((call) => call[0])).toEqual(["/health"]);
});

it("rejects fixture preview when local read-only health is unavailable", async () => {
  window.history.replaceState(null, "", "/?new=1&sx-fixture=auth.code");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ analysis_read_only: false }),
    })),
  );
  function FixtureView() {
    const selected = useProcessingReview(null);
    return <p>{selected.fixtureFrame?.label ?? selected.message}</p>;
  }
  await act(async () => root.render(<FixtureView />));
  expect(container.textContent).toContain(
    "require the read-only review bridge",
  );
  expect(container.textContent).not.toContain("Enter email code");
});
it("rejects duplicate selectors, arbitrary commands and malformed frame IDs", () => {
  expect(reviewFrameId(hash)).toBe(frame);
  for (const bad of [
    hash + "&frame=" + frame,
    hash + "&mode=live",
    hash + "&command=run",
    hash.replace(frame, "nope"),
  ])
    expect(reviewFrameId(bad)).toBeNull();
});
it("accepts only exact local observation routes and allowlisted control facts", () => {
  expect(localReviewFrameId(`?new=1&sx-review-local=${localFrame}`)).toBe(
    localFrame,
  );
  for (const bad of [
    `?new=1&sx-review-local=${localFrame}&sx-review-local=${localFrame}`,
    `?new=1&sx-review-local=${localFrame}&call=${call}`,
    `?new=0&sx-review-local=${localFrame}`,
    `?new=1&sx-review-local=bad`,
  ])
    expect(localReviewFrameId(bad)).toBeNull();
  expect(parseLocalReviewObservation(localBody().observation)).not.toBeNull();
  const validationWithPreviousFile = {
    ...localBody().observation,
    phase: "upload.validation.error",
  };
  expect(
    parseLocalReviewObservation(validationWithPreviousFile),
  ).not.toBeNull();
  expect(
    parseLocalReviewObservation({
      ...validationWithPreviousFile,
      file_size_bytes: null,
    }),
  ).toBeNull();
  expect(
    parseLocalReviewObservation({
      ...localBody().observation,
      filename: "private-call.wav",
    }),
  ).toBeNull();
});
it("uses only the separately authorized observed GET and retains the captured stage", async () => {
  const fetch = mockFetch(() => ({ ok: true, json: async () => body() }));
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<View />));
  expect(container.textContent).toBe("running");
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls.map((call) => call[0])).toEqual([
    "/health",
    `/__review/api/frames/${frame}`,
    "/__review/api/catalog",
  ]);
  expect(fetch.mock.calls.every((call) => !call[1]?.method)).toBe(true);
});
it("masks an expired authorization while a refresh is still hanging", async () => {
  const expiredBody = body();
  expiredBody.leaseUntil = Date.now() + 100;
  const fetch = mockFetch((path) =>
    path === `/__review/api/frames/${frame}`
      ? { ok: true, json: async () => expiredBody }
      : new Promise(() => {}),
  );
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<View />));
  await act(async () => vi.advanceTimersByTimeAsync(101));
  expect(container.textContent).toContain("expired");
  expect(container.textContent).not.toBe("running");
});
it.each(["denied", "source mismatch", "complete", "manual plan"])(
  "rejects %s instead of displaying a plausible fake stage",
  async (kind) => {
    const data = body();
    if (kind === "source mismatch")
      data.receipt.submission_id = "44444444-4444-4444-8444-444444444444";
    if (kind === "complete") data.receipt.has_report = true;
    if (kind === "manual plan") data.receipt.automatic_progression = false;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({ ok: kind !== "denied", json: async () => data }),
    );
    await act(async () => root.render(<View />));
    expect(container.textContent).not.toBe("running");
    expect(container.textContent).toMatch(/cannot|expired|accessible/);
  },
);

it("opens a browser-local state by URL, follows back navigation, and never posts from inspection", async () => {
  window.history.replaceState(
    null,
    "",
    `/?new=1&sx-review-local=${localFrame}`,
  );
  const fetch = mockFetch((path) =>
    path === `/__review/api/local/frames/${localFrame}`
      ? { ok: true, json: async () => localBody() }
      : { ok: true, json: async () => ({}) },
  );
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<CaptureView />));
  expect(container.textContent).toContain("selected file");
  expect(fetch.mock.calls.map((call) => call[0])).toEqual([
    "/health",
    `/__review/api/local/frames/${localFrame}`,
    "/__review/api/local/catalog",
  ]);
  expect(fetch.mock.calls.every((call) => !call[1]?.method)).toBe(true);

  expect(fetch.mock.calls.some((call) => call[1]?.method === "POST")).toBe(
    false,
  );
  window.history.pushState(null, "", "/?new=1");
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));
  expect(container.textContent).toBe("read-only");
});

it("expires an already-open browser-local observation without retaining its label", async () => {
  window.history.replaceState(
    null,
    "",
    `/?new=1&sx-review-local=${localFrame}`,
  );
  const captured = localBody();
  captured.expiresAt = Date.now() + 100;
  const fetch = mockFetch((path) =>
    path === `/__review/api/local/frames/${localFrame}`
      ? { ok: true, json: async () => captured }
      : { ok: true, json: async () => ({}) },
  );
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<View />));
  expect(container.textContent).toContain("Sales call.wav");
  await act(async () => vi.advanceTimersByTimeAsync(101));
  expect(container.textContent).toContain("browser-local observation expired");
  expect(container.textContent).not.toContain("Sales call.wav");
  expect(fetch.mock.calls.every((call) => !call[1]?.method)).toBe(true);
});

it("shows expired local state as unavailable and makes no inspection write", async () => {
  window.history.replaceState(
    null,
    "",
    `/?new=1&sx-review-local=${localFrame}`,
  );
  const fetch = mockFetch((path) =>
    path === `/__review/api/local/frames/${localFrame}`
      ? { ok: false, json: async () => ({}) }
      : { ok: true, json: async () => ({}) },
  );
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<View />));
  expect(container.textContent).toContain("expired or is no longer available");
  expect(fetch.mock.calls.every((call) => !call[1]?.method)).toBe(true);
});

it("publishes only allowlisted local states after read-only mode is confirmed", async () => {
  window.history.replaceState(null, "", "/?new=1");
  const fetch = mockFetch((path) => ({
    ok: true,
    json: async () => (path.endsWith("/observe") ? { id: localFrame } : {}),
  }));
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<CaptureView />));
  const write = fetch.mock.calls.find((call) => call[1]?.method === "POST");
  expect(write?.[0]).toBe("/__review/api/local/observe");
  expect(JSON.parse(write?.[1]?.body as string)).toEqual({
    observation: {
      phase: "upload.empty",
      privacy_open: false,
      consent_checked: false,
      report_language: null,
      verification: "checking",
      file_name: null,
      file_size_bytes: null,
    },
  });
});
