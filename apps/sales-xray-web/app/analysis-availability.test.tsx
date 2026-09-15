// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AnalysisAvailability } from "./analysis-availability";
import { acquisition, ACQUISITION_PAUSED_MESSAGE } from "./acquisition-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
it("shows the paused state, preserves saved-call access copy and offers contact", async () => {
  const onChange = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ paused: true }))),
  );
  await act(async () =>
    root.render(createElement(AnalysisAvailability, { onChange })),
  );
  expect(onChange).toHaveBeenCalledWith(true);
  expect(host.textContent).toContain(
    "Your saved calls and reports are still available",
  );
  expect(host.querySelector("a")?.href).toBe(
    "mailto:admin@authorityclosers.com",
  );
});
it("maps only the server's exact pause message without exposing raw errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: ACQUISITION_PAUSED_MESSAGE }), {
          status: 503,
        }),
    ),
  );
  await expect(acquisition("/submissions/test/plan")).rejects.toMatchObject({
    message: ACQUISITION_PAUSED_MESSAGE,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "private provider response" }), {
          status: 503,
        }),
    ),
  );
  await expect(acquisition("/submissions/test/plan")).rejects.not.toMatchObject(
    { message: "private provider response" },
  );
});
