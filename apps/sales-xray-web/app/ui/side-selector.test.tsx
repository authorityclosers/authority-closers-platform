import { act, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import { SideSelector, type Side } from "./side-selector";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

async function mount(node: ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(node));
}

afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
});

const radios = () =>
  Array.from(host.querySelectorAll<HTMLButtonElement>('[role="radio"]'));

function Held({ onChange }: { onChange: (side: Side) => void }) {
  const [side, setSide] = useState<Side>("inbound");
  return (
    <SideSelector
      value={side}
      onChange={(next) => {
        setSide(next);
        onChange(next);
      }}
      notes={{ inbound: "Fresh enquiries", cold: "Outbound work" }}
    />
  );
}

it("is a two-option radio group, Inbound Leads and Cold Leads", async () => {
  await mount(<SideSelector value="inbound" onChange={vi.fn()} />);
  expect(
    host.querySelector('[role="radiogroup"]')?.getAttribute("aria-label"),
  ).toBe("Lead type");
  expect(radios().map((radio) => radio.textContent)).toEqual([
    "Inbound Leads",
    "Cold Leads",
  ]);
  expect(radios().map((radio) => radio.getAttribute("aria-checked"))).toEqual([
    "true",
    "false",
  ]);
  // Only the chosen one is in the tab order.
  expect(radios().map((radio) => radio.tabIndex)).toEqual([0, -1]);
});

it("picks the other side by tap or arrow key, and says which with a line", async () => {
  const picked = vi.fn();
  await mount(<Held onChange={picked} />);
  expect(host.textContent).toContain("Fresh enquiries");
  await act(async () => radios()[1].click());
  expect(picked).toHaveBeenLastCalledWith("cold");
  expect(radios()[1].getAttribute("aria-checked")).toBe("true");
  expect(host.textContent).toContain("Outbound work");
  // Tapping the chosen side again changes nothing.
  await act(async () => radios()[1].click());
  expect(picked).toHaveBeenCalledTimes(1);
  await act(async () => {
    radios()[1].dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }),
    );
  });
  expect(picked).toHaveBeenLastCalledWith("inbound");
  expect(document.activeElement).toBe(radios()[0]);
});
