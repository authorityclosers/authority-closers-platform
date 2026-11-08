// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ChipRow, CountTabs } from "@ac/ui/kit";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
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
});

// Leads L1 (owner, 8 Nov 2026: "Build L1"): "To call 128 · Follow-ups 12 ·
// All leads 387", one count style on every tab.
it("shows each tab's words and count, the chosen one selected, and changes on another tab only", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <CountTabs
        label="Leads to show"
        items={[
          { key: "to_call", label: "To call", count: 128 },
          { key: "follow_ups", label: "Follow-ups", count: 12 },
          { key: "all", label: "All leads", count: null },
        ]}
        value="to_call"
        onChange={onChange}
        format={(count) => (count > 99 ? `${count}+` : String(count))}
      />,
    ),
  );
  const tabs = [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  expect(
    host.querySelector('[role="tablist"]')?.getAttribute("aria-label"),
  ).toBe("Leads to show");
  expect(tabs.map((tab) => tab.textContent)).toEqual([
    "To call 128+",
    "Follow-ups 12",
    "All leads",
  ]);
  expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual([
    "true",
    "false",
    "false",
  ]);
  await act(async () => tabs[0].click());
  expect(onChange).not.toHaveBeenCalled();
  await act(async () => tabs[1].click());
  expect(onChange).toHaveBeenCalledWith("follow_ups");
});

// Leads L1: the stage chips, a check on the chosen one, Filter pinned at the
// row's end outside the scroll.
it("presses the chosen chip with a check, keeps the end outside the scroll, and changes on another chip only", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <ChipRow
        label="Stage"
        items={[
          { key: "all", label: "All stages", count: 128 },
          { key: "new", label: "New lead", count: 46 },
        ]}
        value="all"
        onChange={onChange}
        end={<button type="button">Filter</button>}
      />,
    ),
  );
  const group = host.querySelector('[role="group"]')!;
  expect(group.getAttribute("aria-label")).toBe("Stage");
  const chips = [...group.querySelectorAll<HTMLButtonElement>("button")];
  expect(chips.map((chip) => chip.textContent)).toEqual([
    "All stages 128",
    "New lead 46",
  ]);
  expect(chips.map((chip) => chip.getAttribute("aria-pressed"))).toEqual([
    "true",
    "false",
  ]);
  expect(chips[0].querySelector("svg")).not.toBeNull();
  expect(chips[1].querySelector("svg")).toBeNull();
  // Filter sits beside the scrolling chips, never inside them.
  const filter = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Filter",
  )!;
  expect(group.contains(filter)).toBe(false);
  await act(async () => chips[0].click());
  expect(onChange).not.toHaveBeenCalled();
  await act(async () => chips[1].click());
  expect(onChange).toHaveBeenCalledWith("new");
});
