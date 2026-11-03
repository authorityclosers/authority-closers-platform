import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ReportScrollRail } from "./report-scroll-rail";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const offsetParent = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "offsetParent",
);

beforeEach(() => {
  // jsdom lays nothing out: the scroller gets room to scroll and each section
  // a parent, as a browser would give them.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("requestAnimationFrame", (run: FrameRequestCallback) =>
    window.setTimeout(() => run(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) =>
    window.clearTimeout(id),
  );
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  host = document.createElement("div");
  host.style.overflowY = "auto";
  Object.defineProperty(host, "scrollHeight", { value: 3000 });
  Object.defineProperty(host, "clientHeight", { value: 800 });
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  if (offsetParent)
    Object.defineProperty(HTMLElement.prototype, "offsetParent", offsetParent);
  vi.unstubAllGlobals();
});

function Report({ sections }: { sections: string[] }) {
  return (
    <>
      {sections.map((title) => (
        <section key={title} data-report-mode-section={title}>
          <h2>{title}</h2>
        </section>
      ))}
      <ReportScrollRail />
    </>
  );
}

const checkpoints = () =>
  [...host.querySelectorAll('button[aria-label^="Go to "]')].map((button) =>
    button.getAttribute("aria-label"),
  );

// The test robot, 855ed149 (3 Nov 2026): after switching to Prospect's
// Information in place, the Report's checkpoints stayed on the rail.
it("follows a view that puts its own sections in place of the last", async () => {
  await act(async () =>
    root.render(
      <Report sections={["1. Overview", "2. Analysis", "3. Outcome"]} />,
    ),
  );
  expect(checkpoints()).toEqual([
    "Go to 1. Overview",
    "Go to 2. Analysis",
    "Go to 3. Outcome",
  ]);
  await act(async () => root.render(<Report sections={["Prospect"]} />));
  await act(async () => new Promise((done) => setTimeout(done, 10)));
  expect(checkpoints()).toEqual([]);
});

// A floating card keeps left of the rail by the room it publishes (855ed149).
it("publishes the room it takes from the right edge while it shows", async () => {
  const room = () =>
    document.documentElement.style.getPropertyValue("--sx-rail-room");
  await act(async () =>
    root.render(<Report sections={["1. Overview", "2. Analysis"]} />),
  );
  expect(room()).toMatch(/^\d+px$/);
  await act(async () => root.unmount());
  root = createRoot(host);
  expect(room()).toBe("");
});
