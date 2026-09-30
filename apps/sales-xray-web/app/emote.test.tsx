// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { Emote } from "./emote";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

it("holds its space while loading and is decorative unless labelled", async () => {
  // No emote file in tests: the placeholder keeps the same size.
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}")));
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<Emote name="handshake" size={24} />));
  const mark = host.firstElementChild as HTMLElement;
  expect(mark.getAttribute("aria-hidden")).toBe("true");
  expect(mark.style.getPropertyValue("--size")).toBe("24px");
  await act(async () =>
    root.render(<Emote name="handshake" size={24} label="Deal closed" />),
  );
  const labelled = host.firstElementChild as HTMLElement;
  expect(labelled.getAttribute("role")).toBe("img");
  expect(labelled.getAttribute("aria-label")).toBe("Deal closed");
  await act(async () => root.unmount());
});
