import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  reviewFrameId,
  useProcessingReview,
} from "./processing-review-port.dev";
import { useProcessingReview as productionPort } from "./processing-review-port";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const call = "11111111-1111-4111-8111-111111111111",
  frame = "33333333-3333-4333-8333-333333333333";
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
function View() {
  const review = useProcessingReview(call);
  return (
    <p>
      {review.frame
        ? review.frame.progress.stages[0].state
        : review.message || "live"}
    </p>
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
    message: "",
  });
  expect(fetch).not.toHaveBeenCalled();
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
it("uses only the separately authorized observed GET and retains the captured stage", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => body() });
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<View />));
  expect(container.textContent).toBe("running");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe(`/__review/api/frames/${frame}`);
  expect(fetch.mock.calls[0][1]).not.toHaveProperty("method");
});
it("masks an expired authorization while a refresh is still hanging", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => body() })
    .mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<View />));
  await act(async () => vi.advanceTimersByTimeAsync(30_001));
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
