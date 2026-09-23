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
  failure_code: null,
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
  refreshProblem: false,
  waitingForApproval: false,
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
  expect(container.textContent).toContain("No new stage update yet");
  expect(container.textContent).not.toMatch(/failed|paused|\d+%/i);
  expect(container.textContent).toContain(
    "does not tell us how much work remains",
  );
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
  expect(vi.getTimerCount()).toBe(1);
  await act(async () => root.render(null));
  expect(vi.getTimerCount()).toBe(0);
});

it("keeps one stable explanation throughout a long wait, without a cycling timer", async () => {
  await render();
  const before = container.querySelector("h3")?.textContent;
  await advance(8_000);
  expect(container.textContent).toContain("source moments");
  await advance(7_200_000);
  expect(container.querySelector("h3")?.textContent).toBe(before);
  expect(container.textContent).toContain("No new stage update yet");
  expect(vi.getTimerCount()).toBe(0);
});

it.each([
  ["C2", "Turning your recording"],
  ["C4", "source moments"],
  ["C5", "Bringing your takeaways"],
])("explains %s only when its latest row is running", async (stage, copy) => {
  await render({
    progress: { ...running, stages: [{ stage, state: "running" }] },
  });
  expect(container.textContent).toContain(copy);
  await render({
    progress: {
      ...running,
      stages: [
        { stage, state: "running" },
        { stage, state: "completed" },
      ],
    },
  });
  expect(container.textContent).not.toContain(copy);
});

it("excludes time spent in a hidden tab from the unchanged foreground notice", async () => {
  await render();
  await advance(30_000);
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "hidden",
  });
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await advance(600_000);
  expect(delayed()).toBe("false");
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await advance(29_999);
  expect(delayed()).toBe("false");
  await advance(1);
  expect(delayed()).toBe("true");
});

it.each(["refreshProblem", "waitingForApproval"] as const)(
  "does not call %s a silent provider wait",
  async (reason) => {
    await render({ [reason]: true });
    await advance(7_200_000);
    expect(container.textContent).not.toContain("No new stage update yet");
    expect(container.textContent).not.toMatch(
      /failed|remaining seconds|percent/i,
    );
  },
);

it("does not rotate copy or add motion when reduced motion is requested", async () => {
  const original = window.matchMedia;
  window.matchMedia = vi.fn().mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  try {
    await render();
    const text = container.textContent;
    await advance(24_000);
    expect(container.textContent).toBe(text);
    expect(vi.getTimerCount()).toBe(1);
  } finally {
    window.matchMedia = original;
  }
});
