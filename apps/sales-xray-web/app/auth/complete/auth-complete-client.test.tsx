// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AUTH_COMPLETE_MESSAGE } from "../../account-auth-client";
import { AuthCompleteClient } from "./auth-complete-client";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  await act(async () => root.render(<AuthCompleteClient flow={flow} />));
  expect(opener.postMessage).toHaveBeenCalledWith(
    { type: AUTH_COMPLETE_MESSAGE, flow },
    window.location.origin,
  );
  expect(JSON.stringify(opener.postMessage.mock.calls)).not.toContain("token");
  expect(host.textContent).toContain("Return to the Sales Xray window");
});

it("sends nothing for an invalid callback flow", async () => {
  const opener = { postMessage: vi.fn() };
  vi.stubGlobal("opener", opener);
  await act(async () => root.render(<AuthCompleteClient flow="//another-origin" />));
  expect(opener.postMessage).not.toHaveBeenCalled();
});
