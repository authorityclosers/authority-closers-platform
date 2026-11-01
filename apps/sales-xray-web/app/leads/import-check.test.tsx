// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import {
  checkLines,
  resultLines,
  ImportCheck,
  skippedCsv,
  SkippedDownload,
} from "./import-check";
import type { Duplicates, ImportPreview } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown 5 (1 Nov 2026): the import's check says what each row
// becomes, with why, before anything is written; numbers already leads are
// skipped unless an owner or admin picks Fill blanks or Replace; the rows an
// import didn't use come back as a file. Made-up people only.
const PREVIEW: ImportPreview = {
  file_name: "fictional-list.csv",
  headers: ["Name", "Phone"],
  rows: [
    { Name: "Asha Example", Phone: "98760 75001" },
    { Name: "Ravi Sample", Phone: "call after 6" },
    { Name: "=Meera Demo", Phone: "98760 75003" },
    { Name: "Asha Again", Phone: "+91 98760 75001" },
    { Name: "Kiran Sample", Phone: "98760 75009" },
    { Name: "", Phone: "" },
  ],
  total_rows: 6,
  truncated: false,
  mapping: { name: "Name", phone: "Phone" },
  with_phone: 4,
  repeats_in_file: 1,
  known_leads: 1,
  importable: 4,
  bad_numbers: 1,
};

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

it("counts each row once, by what it becomes", () => {
  expect(
    checkLines(PREVIEW, 2).map((line) => [line.label, line.count]),
  ).toEqual([
    ["New leads", 2],
    ["Already leads", 1],
    ["Repeated in the file", 1],
    ["Skipped: number can't be read", 1],
    ["Skipped: no name, phone or email", 1],
  ]);
  // Nothing wrong: only the new leads.
  expect(
    checkLines(
      {
        ...PREVIEW,
        total_rows: 2,
        importable: 2,
        repeats_in_file: 0,
        known_leads: 0,
        bad_numbers: 0,
      },
      2,
    ).map((line) => line.label),
  ).toEqual(["New leads"]);
});

it("skips numbers already leads by default, and warns before Fill blanks or Replace", async () => {
  let chosen: Duplicates = "skip";
  const draw = (value: Duplicates) =>
    act(async () =>
      root.render(
        <ImportCheck
          preview={PREVIEW}
          fresh={2}
          canManage
          duplicates={value}
          onDuplicates={(next) => {
            chosen = next;
          }}
        />,
      ),
    );
  await draw("skip");
  const group = host.querySelector('[aria-label="Numbers already leads"]')!;
  const pressed = () =>
    [...group.querySelectorAll('[aria-pressed="true"]')].map(
      (item) => item.textContent,
    );
  expect(pressed()).toEqual(["Skip"]);
  expect(host.textContent).toContain("1 number is already a lead");
  expect(host.textContent).toContain("They stay as they are.");
  const replace = [...group.querySelectorAll("button")].find(
    (item) => item.textContent === "Replace",
  )!;
  await act(async () => replace.click());
  expect(chosen).toBe("replace");
  await draw("replace");
  const warning = host.querySelector('[data-duplicates="replace"]')!;
  expect(warning.textContent).toContain("This can't be undone");
  await draw("fill");
  expect(host.querySelector('[data-duplicates="fill"]')!.textContent).toContain(
    "Their stage and owner stay.",
  );
});

it("offers a seller no choice: numbers already leads stay as they are", async () => {
  await act(async () =>
    root.render(
      <ImportCheck
        preview={PREVIEW}
        fresh={2}
        canManage={false}
        duplicates="skip"
        onDuplicates={() => undefined}
      />,
    ),
  );
  expect(host.querySelector('[aria-label="Numbers already leads"]')).toBeNull();
  expect(host.textContent).toContain("Numbers already leads stay as they are.");
});

it("gives back the skipped rows as the file's own columns plus why, formulas made safe", async () => {
  const skipped = [
    { row: 3, reason: "Repeated in the file" },
    { row: 1, reason: "Number can't be read" },
    { row: 2, reason: "Already a lead" },
  ];
  expect(skippedCsv(PREVIEW, skipped).split("\n")).toEqual([
    '"Name","Phone","Reason"',
    '"Ravi Sample","call after 6","Number can\'t be read"',
    '"\'=Meera Demo","98760 75003","Already a lead"',
    // A phone number keeps its + without the formula guard's apostrophe.
    '"Asha Again","+91 98760 75001","Repeated in the file"',
  ]);
  const result = {
    created: 2,
    repeats: 2,
    skipped: 2,
    assigned: 0,
    waiting: 2,
    skipped_rows: skipped,
  };
  await act(async () =>
    root.render(<SkippedDownload preview={PREVIEW} result={result} />),
  );
  const link = host.querySelector("a")!;
  expect(link.textContent).toBe("Download rows not added (3, with reason)");
  expect(link.getAttribute("download")).toBe("fictional-list-skipped-rows.csv");
  await act(async () =>
    root.render(
      <SkippedDownload
        preview={PREVIEW}
        result={{ ...result, skipped_rows: [] }}
      />,
    ),
  );
  expect(host.querySelector("a")).toBeNull();
});

it("says what became of the rows in the check's words, adding up to the rows", () => {
  const result = {
    created: 2,
    repeats: 2,
    skipped: 1,
    assigned: 0,
    waiting: 2,
    updated: 1,
    skipped_rows: [
      { row: 1, reason: "Number can't be read" },
      { row: 3, reason: "Repeated in the file" },
    ],
  };
  const lines = (duplicates: Duplicates) =>
    resultLines(result, duplicates).map((line) => [line.label, line.count]);
  expect(lines("fill")).toEqual([
    ["New leads", 2],
    ["Already leads", 1],
    ["Details filled in", 1],
    ["Repeated in the file", 1],
    ["Skipped", 1],
  ]);
  expect(lines("replace")[2]).toEqual(["Details replaced", 1]);
  // An answer without reasons says what it can.
  expect(
    resultLines({ ...result, skipped_rows: undefined }, "skip").map(
      (line) => line.label,
    ),
  ).toEqual(["New leads", "Already leads", "Skipped"]);
});
