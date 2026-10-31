import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const reads = vi.hoisted(() => ({
  answers: [] as Array<(value: unknown) => void>,
  failures: [] as Array<(reason: unknown) => void>,
  calls: 0,
}));
vi.mock("./leads-client", () => ({
  readSides: () => {
    reads.calls += 1;
    return new Promise((resolve, reject) => {
      reads.answers.push(resolve);
      reads.failures.push(reject);
    });
  },
}));

const { SIDES_WAIT_MS, forgetSideNumbers, useSideNumbers } = await import(
  "./side-numbers"
);

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const BOTH = {
  inbound: { leads: 3, new: 1, to_call: 2, follow_ups: 1 },
  cold: { imported: 3, unworked: 1, attempted: 2 },
};

function Probe(props: Parameters<typeof useSideNumbers>[0]) {
  return <output>{JSON.stringify(useSideNumbers(props))}</output>;
}

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.useFakeTimers();
  forgetSideNumbers();
  reads.answers.length = 0;
  reads.failures.length = 0;
  reads.calls = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

/** What the hook says now. */
const seen = (): { numbers: unknown; settled: boolean } | null =>
  JSON.parse(host.textContent || "null");

const show = (keyed = "priya:cedar:mine", ready = true) =>
  act(() =>
    root.render(<Probe ready={ready} scope="mine" keyed={keyed} version={0} />),
  );

it("holds the page until the numbers come, so the selector never pushes Search aside (persona QA, 31 Oct 2026)", async () => {
  show();
  expect(seen()).toEqual({ numbers: null, settled: false });
  await act(async () => reads.answers[0](BOTH));
  expect(seen()).toEqual({ numbers: BOTH, settled: true });
});

it("draws without them after the wait, or at once when the read fails", async () => {
  show();
  act(() => vi.advanceTimersByTime(SIDES_WAIT_MS - 1));
  expect(seen()?.settled).toBe(false);
  act(() => vi.advanceTimersByTime(1));
  expect(seen()).toEqual({ numbers: null, settled: true });
  show("priya:maple:mine");
  expect(seen()?.settled).toBe(false);
  await act(async () => reads.failures[1](new Error("offline")));
  expect(seen()).toEqual({ numbers: null, settled: true });
});

it("keeps the last answer, so coming back to Leads draws at once", async () => {
  show();
  await act(async () => reads.answers[0](BOTH));
  act(() => root.unmount());
  root = createRoot(host);
  show();
  expect(seen()).toEqual({ numbers: BOTH, settled: true });
});

it("asks nothing and waits for nothing before there is a role", () => {
  show("signed-out", false);
  expect(reads.calls).toBe(0);
  expect(seen()).toEqual({ numbers: null, settled: true });
});
