// @vitest-environment happy-dom
import { act, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { RailTip } from "./rail-tip";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

function Rail() {
  const rail = useRef<HTMLDivElement | null>(null);
  return (
    <aside>
      <div ref={rail}>
        <button type="button" aria-label="Prospects" data-rail-tip="Prospects">
          <svg aria-hidden="true" />
        </button>
        <button type="button" aria-label="Calls" data-rail-tip="Calls" />
      </div>
      <RailTip rail={rail} />
      {/* The panel beside the rail, drawn later in the page. */}
      <div style={{ position: "relative", zIndex: 99 }}>Recents</div>
    </aside>
  );
}

const label = () => document.body.querySelector("[data-rail-label]");
const pointer = (type: string, target: Element, pointerType = "mouse") =>
  target.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerType }));

beforeEach(async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Rail />));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("draws the hovered icon's label on the page body, outside the sidebar", async () => {
  const icon = host.querySelector("svg") as Element;
  await act(async () => pointer("pointerover", icon));
  expect(label()?.textContent).toBe("Prospects");
  expect(label()?.parentElement).toBe(document.body);
  expect(label()?.getAttribute("aria-hidden")).toBe("true");

  const calls = host.querySelector('[aria-label="Calls"]') as Element;
  await act(async () => pointer("pointerover", calls));
  expect(label()?.textContent).toBe("Calls");

  const rail = host.querySelector("aside > div") as Element;
  await act(async () => pointer("pointerleave", rail));
  expect(label()).toBeNull();
});

it("shows nothing for touch, and Escape hides a label", async () => {
  const icon = host.querySelector("svg") as Element;
  await act(async () => pointer("pointerover", icon, "touch"));
  expect(label()).toBeNull();

  await act(async () => pointer("pointerover", icon));
  expect(label()).not.toBeNull();
  await act(async () =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(label()).toBeNull();
});
