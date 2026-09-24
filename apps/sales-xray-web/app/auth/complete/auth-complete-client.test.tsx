// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AUTH_COMPLETE_MESSAGE } from "../../account-auth-client";
import { AuthCompleteClient } from "./auth-complete-client";

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

it("posts only a flow-bound signal to the exact opener origin", async () => {
  const opener = { postMessage: vi.fn() };
  vi.stubGlobal("opener", opener);
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  await act(async () =>
    root.render(<AuthCompleteClient flow={flow} result="success" />),
  );
  await act(async () => Promise.resolve());
  expect(opener.postMessage).toHaveBeenCalledWith(
    { type: AUTH_COMPLETE_MESSAGE, flow, auth_result: "success" },
    window.location.origin,
  );
  expect(JSON.stringify(opener.postMessage.mock.calls)).not.toContain("token");
  expect(host.textContent).toContain("Return to the Sales Xray window");
  expect(fetcher).not.toHaveBeenCalled();
});

it("sends nothing for an invalid callback flow or result", async () => {
  const opener = { postMessage: vi.fn() };
  vi.stubGlobal("opener", opener);
  await act(async () =>
    root.render(
      <AuthCompleteClient flow="//another-origin" result="success" />,
    ),
  );
  await act(async () =>
    root.render(
      <AuthCompleteClient
        flow="eaed7960-d4d0-4675-bd34-5b6a7d9c598d"
        result={null}
      />,
    ),
  );
  expect(opener.postMessage).not.toHaveBeenCalled();
});

it("forwards failure and review results without requiring a success receipt", async () => {
  const opener = { postMessage: vi.fn() };
  vi.stubGlobal("opener", opener);
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  for (const result of ["failed", "review_terms", "unavailable"] as const) {
    await act(async () =>
      root.render(
        <AuthCompleteClient key={result} flow={flow} result={result} />,
      ),
    );
  }
  expect(
    opener.postMessage.mock.calls.map(([message]) => message.auth_result),
  ).toEqual(["failed", "review_terms", "unavailable"]);
  expect(fetcher).not.toHaveBeenCalled();
});
