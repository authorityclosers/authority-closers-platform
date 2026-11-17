import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it } from "vitest";

import { cantAddCsv, outcomeCounts, rowViews, RowsCheck } from "./import-rows";
import type { Duplicates, FileCheck, ImportPreview } from "./leads-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Lead import I3 (owner's picks, 17 Nov 2026): every row's outcome, four tiles that
// add up to the file's rows and I3-B's bar; a short number fixed in place; the phone's
// own version with the same answers. Made-up people only.
const PREVIEW: ImportPreview = {
  file_name: "expo.csv",
  headers: ["Customer Name", "Mobile No.", "City/Town", "Status"],
  rows: [
    {
      "Customer Name": "Rohit Example",
      "Mobile No.": "99999 00011",
      "City/Town": "Pune",
      Status: "New",
    },
    {
      "Customer Name": "Kavya Sample",
      "Mobile No.": "99999 00012",
      "City/Town": "Mumbai",
    },
    { "Customer Name": "Imran Demo", "Mobile No.": "98765" },
    { "Customer Name": "Rohit Example", "Mobile No.": "99999 00011" },
    { "City/Town": "Thane" },
  ],
  total_rows: 5,
  truncated: false,
  mapping: {
    name: "Customer Name",
    phone: "Mobile No.",
    city: "City/Town",
    stage: "Status",
  },
  with_phone: 4,
  repeats_in_file: 1,
};

const CHECK: FileCheck = {
  stages: [],
  unmatched_stage: null,
  owners: [],
  owned_new: 0,
  columns: [],
  rows: [
    { row: 0, outcome: "new" },
    { row: 1, outcome: "known", lead_id: "l1", lead_name: "Kavya Sample" },
    { row: 2, outcome: "bad" },
    { row: 3, outcome: "repeat", same_as: 0 },
    { row: 4, outcome: "blank" },
  ],
};

let root: Root | undefined;
let host: HTMLDivElement | undefined;

afterEach(async () => {
  const mounted = root;
  if (mounted) await act(async () => mounted.unmount());
  host?.remove();
  root = undefined;
  host = undefined;
});

async function mount(
  narrow: boolean,
  fixed: [number, string][] = [],
  duplicates: Duplicates = "skip",
) {
  const div = document.createElement("div");
  host = div;
  document.body.append(div);
  const made = createRoot(div);
  root = made;
  await act(async () =>
    made.render(
      <RowsCheck
        preview={PREVIEW}
        mapping={PREVIEW.mapping}
        check={CHECK}
        narrow={narrow}
        canManage
        duplicates={duplicates}
        onDuplicates={() => undefined}
        onFix={(row, phone) => fixed.push([row, phone])}
      />,
    ),
  );
  return div;
}

it("gives every row one outcome, and the counts add up to the file", () => {
  const rows = rowViews(PREVIEW, PREVIEW.mapping, CHECK);
  expect(rows.map((row) => row.outcome)).toEqual([
    "new",
    "known",
    "bad",
    "repeat",
    "blank",
  ]);
  const counts = outcomeCounts(rows);
  expect(counts).toEqual({ new: 1, known: 1, repeat: 1, cant: 2 });
  expect(counts.new + counts.known + counts.repeat + counts.cant).toBe(
    PREVIEW.rows.length,
  );
  // The file's own columns, then why (each cell quoted by the CSV guard).
  expect(cantAddCsv(PREVIEW, rows).split("\n")).toEqual([
    '"Customer Name","Mobile No.","City/Town","Status","Reason"',
    '"Imran Demo","98765","","","Number can\'t be read"',
    '"","","Thane","","No name, phone or email"',
  ]);
});

it("shows the tiles, the bar and the rows on a computer, and fixes a number in place", async () => {
  const fixed: [number, string][] = [];
  const view = await mount(false, fixed);
  expect(
    [...view.querySelectorAll("[data-check]")].map((tile) => [
      tile.getAttribute("data-check"),
      tile.querySelector("strong")?.textContent,
    ]),
  ).toEqual([
    ["new", "1"],
    ["known", "1"],
    ["repeat", "1"],
    ["cant", "2"],
  ]);
  expect(view.querySelector("[data-outcome-bar]")?.textContent).toBe(
    "1 new1 already here1 repeated2 can't add",
  );
  const outcomes = [...view.querySelectorAll("tbody tr")].map(
    (row) => row.lastElementChild?.textContent,
  );
  expect(outcomes).toEqual([
    "New",
    "Already here · Kavya Sample",
    "Can't add",
    "Repeated · row 1",
    "Can't add",
  ]);
  // The "Can't be added" tile shows only those rows.
  await act(async () =>
    (view.querySelector('[data-check="cant"]') as HTMLButtonElement).click(),
  );
  expect(view.querySelectorAll("tbody tr")).toHaveLength(2);
  expect(view.textContent).toContain(
    "Rows that can't be added go in a file you can download. Download",
  );
  await act(async () =>
    (
      view.querySelector(
        'button[aria-label="Fix the number for row 3"]',
      ) as HTMLButtonElement
    ).click(),
  );
  const input = view.querySelector<HTMLInputElement>(
    'input[aria-label="Phone number for row 3"]',
  )!;
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    set.call(input, "98765 43210");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    input.form!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ),
  );
  expect(fixed).toEqual([[2, "98765 43210"]]);
  // Owners and admins choose what happens to leads already here.
  expect(view.textContent).toContain("1 row is already a lead");
});

it("gives the phone the same answers: ready line, bar, outcome rows and a Fix card", async () => {
  const view = await mount(true, [], "fill");
  expect(view.querySelector("h3")?.textContent).toBe("1 new lead is ready");
  expect(view.querySelector("[data-outcome-bar]")).not.toBeNull();
  expect(
    [...view.querySelectorAll("[data-check]")].map(
      (row) => row.querySelector("button")?.textContent,
    ),
  ).toEqual([
    "1already in Sales X-Rayempty details filled",
    "1repeated in your fileadded once",
    "2can't be addedno name, phone or email",
  ]);
  await act(async () =>
    (
      view.querySelector('[data-check="known"] button') as HTMLButtonElement
    ).click(),
  );
  expect(view.textContent).toContain("Already here as Kavya Sample");
  expect(view.querySelector('[data-fix-row="2"]')?.textContent).toContain(
    "phone looks shortImran Demo · 98765",
  );
});
