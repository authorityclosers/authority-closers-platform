// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { signalWebReady, WebReady } from "./web-ready";

afterEach(() => {
  delete (globalThis as { SXPhone?: unknown }).SXPhone;
});

it("tells the phone app the page is up, once it has started", () => {
  const postMessage = vi.fn();
  (globalThis as { SXPhone?: unknown }).SXPhone = {
    postMessage,
    addEventListener: vi.fn(),
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  act(() => root.render(<WebReady />));
  expect(postMessage).toHaveBeenCalledTimes(1);
  const message = JSON.parse(postMessage.mock.calls[0][0] as string) as {
    method: string;
    id: string;
    args: { release: string };
  };
  expect(message.method).toBe("webReady");
  expect(message.id).toBe("web-ready");
  expect(typeof message.args.release).toBe("string");
  act(() => root.unmount());
  host.remove();
});

it("does nothing outside the app or when the app's channel refuses", () => {
  expect(signalWebReady(undefined)).toBe(false);
  expect(signalWebReady({})).toBe(false);
  expect(
    signalWebReady({
      postMessage: () => {
        throw new Error("gone");
      },
    }),
  ).toBe(false);
});
