import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  leavingOverlay,
  OVERLAY_DEPTH_KEY,
  resetBackCloseForTests,
  useBackClose,
} from "./back-close";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Overlay({
  name,
  open,
  onClose,
}: {
  name: string;
  open: boolean;
  onClose: () => void;
}) {
  useBackClose(open, onClose);
  return open ? <p>{name}</p> : null;
}

function Host({ keep = false }: { keep?: boolean }) {
  const [first, setFirst] = useState(false);
  const [second, setSecond] = useState(false);
  return (
    <>
      <button type="button" id="open" onClick={() => setFirst(true)} />
      <button type="button" id="close" onClick={() => setFirst(false)} />
      <button
        type="button"
        id="swap"
        onClick={() => {
          setFirst(false);
          setSecond(true);
        }}
      />
      <Overlay
        name="First"
        open={first}
        onClose={() => {
          if (!keep) setFirst(false);
        }}
      />
      <Overlay name="Second" open={second} onClose={() => setSecond(false)} />
    </>
  );
}

let root: Root;
let host: HTMLDivElement;
const depth = () =>
  ((window.history.state as Record<string, unknown> | null)?.[
    OVERLAY_DEPTH_KEY
  ] as number | undefined) ?? 0;
const settle = () => act(async () => Promise.resolve());
const tap = (id: string) =>
  act(async () => host.querySelector<HTMLButtonElement>(`#${id}`)!.click());

async function mount(keep = false) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Host keep={keep} />));
}

beforeEach(() => {
  window.history.replaceState(null, "", "/leads");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.restoreAllMocks();
});

it("adds one history entry per open overlay, and Back closes it", async () => {
  await mount();
  await tap("open");
  await settle();
  expect(depth()).toBe(1);
  expect(host.textContent).toContain("First");
  await act(async () => window.history.back());
  await settle();
  expect(host.textContent).not.toContain("First");
  expect(depth()).toBe(0);
  expect(window.location.pathname).toBe("/leads");
});

it("takes its entry back off when closed by a tap, so Back never stops on the same page", async () => {
  await mount();
  await tap("open");
  await settle();
  await tap("close");
  await settle();
  expect(depth()).toBe(0);
});

it("hands its entry to the overlay that opens as it closes", async () => {
  await mount();
  await tap("open");
  await settle();
  const push = vi.spyOn(window.history, "pushState");
  const go = vi.spyOn(window.history, "go");
  await tap("swap");
  await settle();
  expect(push).not.toHaveBeenCalled();
  expect(go).not.toHaveBeenCalled();
  expect(depth()).toBe(1);
  expect(host.textContent).toContain("Second");
  await act(async () => window.history.back());
  await settle();
  expect(host.textContent).not.toContain("Second");
});

it("leaves the entry to a link that leaves, and Back later steps over it", async () => {
  await mount();
  await tap("open");
  await settle();
  leavingOverlay();
  await tap("close");
  await settle();
  // The next page covers the overlay's entry.
  expect(depth()).toBe(1);
  window.history.pushState(null, "", "/dashboard");
  await act(async () => window.history.back());
  await settle();
  expect(window.location.pathname).toBe("/leads");
  expect(depth()).toBe(0);
});

it("arms again when its owner keeps it open", async () => {
  await mount(true);
  await tap("open");
  await settle();
  await act(async () => window.history.back());
  await settle();
  expect(host.textContent).toContain("First");
  expect(depth()).toBe(1);
});
