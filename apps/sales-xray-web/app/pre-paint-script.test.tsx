// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

import { PrePaintScript } from "./pre-paint-script";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

const script = (
  <PrePaintScript id="sales-xray-test-init" code="window.__x = 1" />
);

// QA robot 6fa0427f (1 Nov 2026): "Encountered a script tag while rendering
// React component", 20 times on Home, when the root rendered again on the client.
it("is in the server's HTML and kept by hydration, never written later on the client", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  const html = renderToString(script);
  expect(html).toBe(
    '<script id="sales-xray-test-init">window.__x = 1</script>',
  );

  const served = document.createElement("div");
  served.innerHTML = html;
  document.body.append(served);
  let root: Root | null = null;
  await act(async () => {
    root = hydrateRoot(served, script);
  });
  expect(served.querySelector("script#sales-xray-test-init")).not.toBeNull();
  await act(async () => root?.unmount());

  // The root again from scratch (after an error, a dev reload): no script.
  const again = document.createElement("div");
  document.body.append(again);
  const fresh = createRoot(again);
  await act(async () => fresh.render(script));
  expect(again.querySelector("script")).toBeNull();
  await act(async () => fresh.unmount());

  expect(errors.mock.calls.flat().join(" ")).not.toMatch(/script tag/i);
});
