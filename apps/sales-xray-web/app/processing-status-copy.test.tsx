import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Progress } from "./acquisition-client";
import { ProcessingStatusCopy } from "./processing-status-copy";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const running: Progress = {
  state: "active",
  local_state: "completed",
  has_report: false,
  automatic_progression: true,
  stages: [
    { stage: "C2", state: "completed" },
    { stage: "C4", state: "running" },
  ],
};
const defaults = {
  submissionId: "call-a",
  progress: running,
  title: "Checking the conversation",
  paused: false,
  needsAttention: false,
};
async function render(props: Partial<typeof defaults> = {}) {
  await act(async () =>
    root.render(<ProcessingStatusCopy {...defaults} {...props} />),
  );
}
async function advance(ms: number) {
  await act(async () => vi.advanceTimersByTimeAsync(ms));
}
const delayed = () =>
  container
    .querySelector("[data-update-delayed]")
    ?.getAttribute("data-update-delayed");

beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

it("waits one minute, preserving the real stage title without a failure or percentage", async () => {
  await render();
  await advance(59_999);
  expect(delayed()).toBe("false");
  await advance(1);
  expect(delayed()).toBe("true");
  expect(container.querySelector("h3")?.textContent).toBe(defaults.title);
  expect(container.textContent).toContain("WAITING FOR AN UPDATE");
  expect(container.textContent).not.toMatch(/failed|paused|\d+%/i);
  const messages = container.querySelectorAll("[data-visible]");
  expect(messages).toHaveLength(4);
  expect(messages[0].getAttribute("aria-hidden")).toBe("true");
  expect(messages[3].hasAttribute("aria-hidden")).toBe(false);
  expect(messages[3].textContent).toContain("no need to upload again");
});

it("does not reset the wait when an identical poll returns a new object", async () => {
  await render();
  await advance(30_000);
  await render({ progress: structuredClone(running) });
  await advance(30_000);
  expect(delayed()).toBe("true");
});

it("resets on a stage change and counts a fresh minute", async () => {
  await render();
  await advance(60_000);
  await render({
    progress: {
      ...running,
      stages: [...running.stages, { stage: "C5", state: "running" }],
    },
  });
  expect(delayed()).toBe("false");
  await advance(59_999);
  expect(delayed()).toBe("false");
  await advance(1);
  expect(delayed()).toBe("true");
});

it("resets on additional work within the same stage, not only the visible heading", async () => {
  await render();
  await advance(60_000);
  await render({
    progress: {
      ...running,
      stages: [
        ...running.stages,
        { stage: "C4", state: "completed" },
        { stage: "C4", state: "running" },
      ],
    },
  });
  expect(delayed()).toBe("false");
  expect(container.querySelector("h3")?.textContent).toBe(defaults.title);
});

it("resets on a different submission or automatic-progression state", async () => {
  await render();
  await advance(60_000);
  await render({ submissionId: "call-b" });
  expect(delayed()).toBe("false");
  await advance(60_000);
  await render({
    submissionId: "call-b",
    progress: { ...running, automatic_progression: false },
  });
  expect(delayed()).toBe("false");
});

it("gives paused and error guidance priority and restarts the timer only on return to active", async () => {
  await render();
  await advance(60_000);
  await render({ needsAttention: true, paused: true });
  expect(delayed()).toBeUndefined();
  expect(container.textContent).toContain("Analysis paused");
  await advance(120_000);
  expect(container.textContent).not.toContain("WAITING FOR AN UPDATE");
  await render({ needsAttention: true });
  expect(container.textContent).toContain("Your call needs attention");
  await render();
  expect(delayed()).toBe("false");
});

it("cleans up the timer when removed for a completed report or navigation", async () => {
  await render();
  expect(vi.getTimerCount()).toBe(2);
  await act(async () => root.render(null));
  expect(vi.getTimerCount()).toBe(0);
});

it("rotates same-stage cues without changing the real title, then stops cycling after the delayed notice", async () => {
  await render();
  const visible = () =>
    container.querySelector('[data-visible="true"]')?.textContent;
  expect(visible()).toContain("Reviewing the conversation");
  await advance(8_000);
  expect(visible()).toContain("source moments");
  expect(container.querySelector("h3")?.textContent).toBe(defaults.title);
  await advance(8_000);
  expect(visible()).toContain("Your call is saved");
  await advance(44_000);
  expect(visible()).toContain("No new stage update yet");
  expect(vi.getTimerCount()).toBe(0);
});

it.each([
  ["C2", "Turning your recording"],
  ["C4", "Reviewing the conversation"],
  ["C5", "Bringing your takeaways"],
])("shows %s cues only when that stage is running", async (stage, copy) => {
  await render({
    progress: { ...running, stages: [{ stage, state: "running" }] },
  });
  expect(
    container.querySelector('[data-visible="true"]')?.textContent,
  ).toContain(copy);
  await render({
    progress: { ...running, stages: [{ stage, state: "queued" }] },
  });
  expect(
    container.querySelector('[data-visible="true"]')?.textContent,
  ).toContain("Waiting for the next stage");
});

it("uses recording-check cues before local validation completes", async () => {
  await render({
    progress: { ...running, local_state: "running", stages: [] },
  });
  expect(
    container.querySelector('[data-visible="true"]')?.textContent,
  ).toContain("format and duration");
});

it("does not cycle informational cues when reduced motion is requested", async () => {
  const original = window.matchMedia;
  window.matchMedia = vi.fn().mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  try {
    await render();
    await advance(24_000);
    expect(
      container.querySelector('[data-visible="true"]')?.textContent,
    ).toContain("Reviewing the conversation");
    expect(vi.getTimerCount()).toBe(1);
  } finally {
    window.matchMedia = original;
  }
});
