import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UploadCheck } from "./upload-check";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement;
beforeEach(() => {
  // The harness drives load/error events explicitly and never fetches scripts.
  (
    window as unknown as {
      happyDOM: { settings: { handleDisabledFileLoadingAsSuccess: boolean } };
    }
  ).happyDOM.settings.handleDisabledFileLoadingAsSuccess = true;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  delete window.turnstile;
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  delete window.turnstile;
  vi.restoreAllMocks();
});

it("retries a failed widget script without reloading or losing the selected call", async () => {
  const onToken = vi.fn();
  await act(async () =>
    root.render(
      <UploadCheck
        siteKey="synthetic-public-key"
        action="sales_xray_upload"
        onToken={onToken}
      />,
    ),
  );
  const original = document.querySelector<HTMLScriptElement>(
    'script[src*="challenges.cloudflare.com"]',
  )!;
  await act(async () => original.dispatchEvent(new Event("error")));
  expect(container.textContent).toContain("Retry check");
  await act(async () => container.querySelector("button")!.click());
  const replacement = document.querySelector<HTMLScriptElement>(
    'script[src*="challenges.cloudflare.com"]',
  )!;
  expect(replacement).not.toBe(original);
  let options: Record<string, unknown> = {};
  window.turnstile = {
    render: vi.fn((_element, next) => {
      options = next;
      return "test-widget";
    }),
    remove: vi.fn(),
  };
  await act(async () => replacement.dispatchEvent(new Event("load")));
  expect(options.sitekey).toBe("synthetic-public-key");
  expect(options.action).toBe("sales_xray_upload");
  await act(async () =>
    (options.callback as (value: string) => void)("synthetic-response"),
  );
  expect(onToken).toHaveBeenLastCalledWith("synthetic-response");
  await act(async () => (options["expired-callback"] as () => void)());
  expect(onToken).toHaveBeenLastCalledWith("");
});
