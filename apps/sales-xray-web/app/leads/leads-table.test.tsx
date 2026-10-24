// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { LeadRow } from "./leads-client";
import { LeadsTable } from "./leads-table";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Leads as a table on a computer (owner P0, 23 Oct 2026): one lead per line,
// sortable, the same rows and taps as the list.
const id = (index: number) =>
  `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;

const row = (index: number, overrides: Partial<LeadRow> = {}): LeadRow => ({
  lead_id: id(index),
  revision: 1,
  name: "meera fictional",
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New enquiry",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: "swamini fictional",
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

const headers = () =>
  Array.from(host.querySelectorAll("thead th"), (cell) =>
    cell.textContent?.trim(),
  );
const names = () =>
  Array.from(host.querySelectorAll("tbody tr strong"), (cell) =>
    cell.textContent?.trim(),
  );

it("shows each lead on one line, with names capitalised and the columns asked for", async () => {
  const onOpen = vi.fn();
  await act(async () =>
    root.render(
      <LeadsTable
        rows={[
          row(1, {
            calls: 2,
            last_result_label: "Busy",
            company: "Fictional Homes",
          }),
          row(2, { name: "ravi sample", owner_name: null, phone_last4: null }),
        ]}
        onOpen={onOpen}
        showOwner
        pipelineNames={
          new Map([
            ["main", "Enrolment"],
            ["partner_outreach", "Partner outreach"],
          ])
        }
      />,
    ),
  );
  expect(headers()).toEqual([
    "Name",
    "Phone",
    "Stage",
    "Pipeline",
    "Owner",
    "Source",
    "Next action",
    "Last call",
    "In stage",
  ]);
  const first = host.querySelector("tbody tr")!;
  expect(first.textContent).toContain("Meera Fictional");
  expect(first.textContent).toContain("Fictional Homes");
  expect(first.textContent).toContain("•• 3210");
  expect(first.textContent).toContain("Enrolment");
  expect(first.textContent).toContain("Swamini Fictional");
  expect(first.textContent).toContain("Busy · 2 calls");
  const second = host.querySelectorAll("tbody tr")[1];
  expect(second.textContent).toContain("No number");
  expect(second.textContent).toContain("No owner");
  expect(second.textContent).toContain("Not called");
  // A line's tap opens the lead; its name is the row key's stop.
  await act(async () => (second as HTMLElement).click());
  expect(onOpen).toHaveBeenCalledWith(id(2));
  expect(
    host.querySelector(`[data-row-key="${id(1)}"]`)?.tagName.toLowerCase(),
  ).toBe("button");
});

it("leaves out Owner on my own leads and Pipeline with one pipeline", async () => {
  await act(async () =>
    root.render(
      <LeadsTable rows={[row(1)]} onOpen={() => undefined} showOwner={false} />,
    ),
  );
  expect(headers()).toEqual([
    "Name",
    "Phone",
    "Stage",
    "Source",
    "Next action",
    "Last call",
    "In stage",
  ]);
});

// Lead OS: a column picker this browser remembers.
it("shows and hides columns from the picker", async () => {
  await act(async () =>
    root.render(
      <LeadsTable rows={[row(1)]} onOpen={() => undefined} showOwner={false} />,
    ),
  );
  const pick = (label: string) =>
    Array.from(host.querySelectorAll("label"))
      .find((item) => item.textContent?.trim() === label)
      ?.querySelector("input");
  await act(async () =>
    Array.from(host.querySelectorAll("button"))
      .find((button) => button.textContent?.trim() === "Columns")
      ?.click(),
  );
  await act(async () => pick("Phone")?.click());
  await act(async () => pick("Reason")?.click());
  expect(headers()).toEqual([
    "Name",
    "Stage",
    "Source",
    "Next action",
    "Last call",
    "In stage",
    "Reason",
  ]);
  // Kept for this browser; the next test starts from the first columns.
  expect(window.localStorage.getItem("sx-leads-table-columns")).toContain(
    "reason",
  );
  window.localStorage.removeItem("sx-leads-table-columns");
});

it("sorts by a column, then the other way, then back to the list's order", async () => {
  await act(async () =>
    root.render(
      <LeadsTable
        rows={[
          row(1, { name: "meera fictional" }),
          row(2, { name: "asha example" }),
          row(3, { name: "ravi sample" }),
        ]}
        onOpen={() => undefined}
        showOwner={false}
      />,
    ),
  );
  const sortBy = async (label: string) => {
    const button = Array.from(host.querySelectorAll("thead button")).find(
      (item) => item.textContent?.trim() === label,
    ) as HTMLButtonElement;
    await act(async () => button.click());
  };
  await sortBy("Name");
  expect(names()).toEqual(["Asha Example", "Meera Fictional", "Ravi Sample"]);
  expect(
    host.querySelector('th[data-column="name"]')?.getAttribute("aria-sort"),
  ).toBe("ascending");
  await sortBy("Name");
  expect(names()).toEqual(["Ravi Sample", "Meera Fictional", "Asha Example"]);
  await sortBy("Name");
  expect(names()).toEqual(["Meera Fictional", "Asha Example", "Ravi Sample"]);
});

it("ticks leads while selecting instead of opening them", async () => {
  const onOpen = vi.fn();
  const onToggle = vi.fn();
  await act(async () =>
    root.render(
      <LeadsTable
        rows={[row(1), row(2)]}
        onOpen={onOpen}
        showOwner={false}
        selecting
        chosen={new Map([[id(2), "meera fictional"]])}
        onToggle={onToggle}
      />,
    ),
  );
  const boxes = host.querySelectorAll<HTMLInputElement>(
    'tbody input[type="checkbox"]',
  );
  expect(Array.from(boxes, (box) => box.checked)).toEqual([false, true]);
  await act(async () =>
    (host.querySelector("tbody tr") as HTMLElement).click(),
  );
  expect(onToggle).toHaveBeenCalledWith(
    expect.objectContaining({ lead_id: id(1) }),
  );
  expect(onOpen).not.toHaveBeenCalled();
});
