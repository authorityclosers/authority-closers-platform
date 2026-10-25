// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SelectBar } from "./delete-leads";
import type { LeadRow } from "./leads-client";
import { LeadsTable } from "./leads-table";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The owner's Leads table batch (25 Oct 2026, production v0.90 on a computer).
const row = (overrides: Partial<LeadRow> = {}): LeadRow => ({
  lead_id: "00000000-0000-4000-8000-000000000001",
  revision: 1,
  name: "indentura fictional enterprises",
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "0815",
  stage: "new",
  stage_label: "New enquiry",
  source: "manual",
  source_label: "Website enquiry form, partner campaign",
  owner_person_id: null,
  owner_name: "kavya fictional",
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-22T06:30:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  pipeline: "main",
  ...overrides,
});

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

it("names select mode's actions and says what to do first", async () => {
  const onAssign = vi.fn();
  const onMove = vi.fn();
  const render = (count: number) =>
    act(async () =>
      root.render(
        <SelectBar
          count={count}
          total={524}
          loaded={50}
          busy={false}
          onAll={() => {}}
          onClear={() => {}}
          onDelete={() => {}}
          onActions={() => {}}
          onAssign={onAssign}
          onMove={onMove}
        />,
      ),
    );
  await render(0);
  expect(host.textContent).toContain(
    "Tick the leads to change, then choose what to do",
  );
  const buttons = () =>
    Array.from(host.querySelectorAll("button"), (button) => [
      button.textContent?.trim(),
      button.disabled,
    ]);
  expect(buttons()).toEqual([
    ["Select the first 500", false],
    ["Assign to…", true],
    ["Move stage", true],
    ["More", true],
    ["Delete", true],
  ]);
  await render(3);
  expect(host.textContent).toContain("3 selected");
  const assign = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Assign to…",
  )!;
  await act(async () => assign.click());
  expect(onAssign).toHaveBeenCalledOnce();
});

it("slides a cut cell to show its end while the pointer rests on it", async () => {
  await act(async () =>
    root.render(<LeadsTable rows={[row()]} onOpen={() => {}} showOwner />),
  );
  const source = host.querySelector<HTMLElement>(
    'td[data-column="source"] [data-cell-text]',
  )!;
  Object.defineProperty(source, "scrollWidth", { value: 240 });
  Object.defineProperty(source, "clientWidth", { value: 120 });
  await act(async () =>
    source.dispatchEvent(new Event("pointerover", { bubbles: true })),
  );
  const cell = source.closest("td")!;
  expect(cell.hasAttribute("data-slide")).toBe(true);
  expect(cell.style.getPropertyValue("--slide")).toBe("-120px");
  await act(async () =>
    source.dispatchEvent(new Event("pointerout", { bubbles: true })),
  );
  expect(cell.hasAttribute("data-slide")).toBe(false);
  // The whole name on hover.
  expect(host.querySelector("tbody strong")?.getAttribute("title")).toBe(
    "Indentura Fictional Enterprises",
  );
});
