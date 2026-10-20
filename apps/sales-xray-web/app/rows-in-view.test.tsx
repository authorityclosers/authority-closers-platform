import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { useRowsInView } from "./rows-in-view";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true;

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("counts every row where nothing can tell what is on screen (and under test)", async () => {
  let seen: Set<string> | null | undefined;
  function Rows() {
    seen = useRowsInView(true).seen;
    return null;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Rows />));
  expect(seen).toBeNull();
  await act(async () => root.unmount());
});

it("adds a row once it comes on screen, and only then", async () => {
  vi.stubEnv("NODE_ENV", "production");
  let report: (entries: { isIntersecting: boolean; target: Element }[]) => void =
    () => {};
  const observed: Element[] = [];
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: typeof report) {
        report = callback;
      }
      observe(element: Element) {
        observed.push(element);
      }
      disconnect() {}
    },
  );
  let seen: Set<string> | null = null;
  function Rows() {
    const rows = useRowsInView(true);
    seen = rows.seen;
    return (
      <>
        {["a", "b"].map((id) => (
          <div key={id} data-call-row={id} ref={rows.observeRow} />
        ))}
      </>
    );
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Rows />));
  expect(observed).toHaveLength(2);
  expect([...(seen ?? [])]).toEqual([]);
  await act(async () =>
    report([
      { isIntersecting: true, target: observed[1] },
      { isIntersecting: false, target: observed[0] },
    ]),
  );
  expect([...(seen ?? [])]).toEqual(["b"]);
  await act(async () => root.unmount());
});
