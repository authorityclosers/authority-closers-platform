// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { DidntLoad, LOAD_DEADLINE_MS, useLoadDeadline } from "./didnt-load";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});

function Probe({ loading }: { loading: boolean }) {
  const late = useLoadDeadline(loading);
  return <p>{late ? "late" : loading ? "loading" : "done"}</p>;
}

// v1.96 device polish, lane P: no screen says "Loading…" for ever on a 502.
it("counts a read still loading after 8 s as failed, and forgets it once it answers", async () => {
  await act(async () => root.render(<Probe loading />));
  expect(host.textContent).toBe("loading");
  await act(async () => vi.advanceTimersByTime(LOAD_DEADLINE_MS - 1));
  expect(host.textContent).toBe("loading");
  await act(async () => vi.advanceTimersByTime(1));
  expect(host.textContent).toBe("late");
  await act(async () => root.render(<Probe loading={false} />));
  expect(host.textContent).toBe("done");
});

it("says what didn't load, once, with Try again", async () => {
  const retry = vi.fn();
  await act(async () =>
    root.render(<DidntLoad what="Your plan" onRetry={retry} />),
  );
  expect(host.querySelector("[role=alert]")?.textContent).toContain(
    "Your plan didn't load",
  );
  await act(async () => host.querySelector("button")!.click());
  expect(retry).toHaveBeenCalledTimes(1);
});
