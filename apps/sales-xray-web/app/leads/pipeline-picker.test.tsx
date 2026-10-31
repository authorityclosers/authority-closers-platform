import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { PipelinePicker } from "./pipeline-picker";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, Admin #3, 26 Oct 2026: the picker fills the row, never a chip on the
// left and an empty right.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const TWO = [
  { key: "main", name: "Enquiries" },
  { key: "partner_outreach", name: "Partner outreach" },
];

it("shows up to three pipelines as one segmented control with All", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <PipelinePicker pipelines={TWO} value={null} onChange={onChange} />,
    ),
  );
  const buttons = [...host.querySelectorAll("button")];
  expect(buttons.map((button) => button.textContent)).toEqual([
    "All",
    "Enquiries",
    "Partner outreach",
  ]);
  expect(buttons[0].getAttribute("aria-pressed")).toBe("true");
  expect(host.querySelector('[role="group"]')?.getAttribute("aria-label")).toBe(
    "Pipeline to call",
  );
  await act(async () => buttons[2].click());
  expect(onChange).toHaveBeenLastCalledWith("partner_outreach");
  await act(async () => buttons[0].click());
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(host.querySelector("select")).toBeNull();
});

it("keeps more pipelines in a menu", async () => {
  const onChange = vi.fn();
  const four = [
    ...TWO,
    { key: "renewals", name: "Renewals" },
    { key: "events", name: "Events" },
  ];
  await act(async () =>
    root.render(
      <PipelinePicker pipelines={four} value="events" onChange={onChange} />,
    ),
  );
  const button = host.querySelector<HTMLButtonElement>(
    'button[aria-haspopup="listbox"]',
  )!;
  expect(button.getAttribute("data-value")).toBe("events");
  expect(host.querySelector('[role="group"]')).toBeNull();
  await act(async () => button.click());
  expect(host.querySelectorAll('[role="option"]')).toHaveLength(5);
  await act(async () =>
    host.querySelector<HTMLElement>('[role="option"][data-key=""]')!.click(),
  );
  expect(onChange).toHaveBeenLastCalledWith(null);
});
