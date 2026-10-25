// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { LeadRow } from "./leads-client";
import { fitColumns, LeadsTable } from "./leads-table";

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

it("shows the whole number when the organisation shows full numbers", async () => {
  await act(async () =>
    root.render(
      <LeadsTable
        rows={[row(1, { phone: "+919876543210" }), row(2)]}
        onOpen={vi.fn()}
        showOwner={false}
      />,
    ),
  );
  const [first, second] = host.querySelectorAll("tbody tr");
  expect(first.textContent).toContain("+91 98765 43210");
  expect(first.textContent).not.toContain("•• 3210");
  expect(second.textContent).toContain("•• 3210");
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

// Phones (owner, 25 Oct 2026: "sideways scrolling is hard"): the key columns
// that fit stay in the row, the rest open under it; nothing scrolls sideways.
it("fits Name and the key columns to the pane's width", () => {
  const shown = ["phone", "stage", "source", "next", "last", "age"];
  const order = ["stage", "next", "owner", "last", "source", "age", "phone"];
  expect(fitColumns(0, shown, order, false)).toBeNull();
  expect(fitColumns(900, shown, order, false)).toBeNull();
  // A 360 px phone leaves 328 and a 390 px one 358: Name and Stage (with the
  // next action under it), 144 px, the rest (140 and 170) for the name.
  expect(fitColumns(328, shown, order, false)).toEqual({
    keys: ["stage"],
    keyWidth: 144,
  });
  expect(fitColumns(358, shown, order, false)).toEqual({
    keys: ["stage"],
    keyWidth: 144,
  });
  // The tick column while selecting still leaves room for Stage at 390.
  expect(fitColumns(358, shown, order, true)?.keys).toEqual(["stage"]);
  // 130% text on a small phone: no room for a column; all goes under the name.
  expect(fitColumns(234, shown, order, false)?.keys).toEqual([]);
  // A tablet holds four, in the table's own order.
  expect(fitColumns(736, shown, order, false)).toEqual({
    keys: ["stage", "source", "next", "last"],
    keyWidth: 140,
  });
});

const atWidth = async (width: number, run: () => Promise<void>) => {
  const before = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "clientWidth",
  );
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get: () => width,
  });
  try {
    await run();
  } finally {
    if (before)
      Object.defineProperty(HTMLElement.prototype, "clientWidth", before);
    else delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
  }
};

it("opens the columns that don't fit under a row, without opening the lead", async () => {
  const onOpen = vi.fn();
  await atWidth(358, async () => {
    await act(async () =>
      root.render(
        <LeadsTable
          rows={[
            row(1, { next_action_at: "2026-10-25T10:00:00Z" }),
            row(2, { name: "ravi sample" }),
          ]}
          onOpen={onOpen}
          showOwner={false}
        />,
      ),
    );
    expect(host.querySelector("[data-fit]")).not.toBeNull();
    expect(headers()).toEqual(["Name", "Stage · next", "More"]);
    // Stage carries the next action; without one it says so.
    expect(host.querySelectorAll("tbody tr")[1].textContent).toContain(
      "No next step",
    );
    expect(host.textContent).toContain("3 more columns under each row");
    // No pencil beside a narrow name: renaming is on the lead page.
    expect(host.querySelector('[aria-label^="Rename"]')).toBeNull();
    const more = host.querySelector<HTMLButtonElement>(
      'button[aria-label="Show more about Meera Fictional"]',
    )!;
    await act(async () => more.click());
    expect(onOpen).not.toHaveBeenCalled();
    expect(more.getAttribute("aria-expanded")).toBe("true");
    const under = host.querySelector(`#more-${id(1)}`)!;
    expect(
      Array.from(under.querySelectorAll("dt"), (term) => term.textContent),
    ).toEqual(["Phone", "Source", "Last call"]);
    expect(under.textContent).toContain("•• 3210");
    // Only that row opened; the name still opens the lead.
    expect(host.querySelector(`#more-${id(2)}`)).toBeNull();
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>(`[data-row-key="${id(2)}"]`)!
        .click(),
    );
    expect(onOpen).toHaveBeenCalledWith(id(2));
    await act(async () => more.click());
    expect(host.querySelector(`#more-${id(1)}`)).toBeNull();
  });
});

it("puts stage and next step under the name when no column fits", async () => {
  await atWidth(234, async () => {
    await act(async () =>
      root.render(
        <LeadsTable
          rows={[row(1, { stage_label: "Follow up" })]}
          onOpen={() => undefined}
          showOwner={false}
        />,
      ),
    );
    expect(headers()).toEqual(["Name", "More"]);
    expect(host.querySelector("tbody tr small")?.textContent).toBe("Follow up");
  });
});
