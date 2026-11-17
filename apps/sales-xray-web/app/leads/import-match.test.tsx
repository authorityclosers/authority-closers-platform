import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { FileCheck, ImportPreview } from "./leads-client";

const previewImport = vi.fn();
const commitImport = vi.fn();
const checkFile = vi.fn();
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  previewImport: (...args: unknown[]) => previewImport(...args),
  commitImport: (...args: unknown[]) => commitImport(...args),
  checkFile: (...args: unknown[]) => checkFile(...args),
  readTeam: async () => ({
    reps: [
      {
        person_id: "p1",
        name: "Asha Example",
        role: "seller",
        available: true,
      },
      {
        person_id: "p0",
        name: "Owner Example",
        role: "owner",
        available: false,
      },
    ],
  }),
  readImports: async () => [],
}));
vi.mock("./journey/journey-client", async (original) => ({
  ...(await original<typeof import("./journey/journey-client")>()),
  readJourney: async () => ({
    stages: [
      { key: "new", label: "New Lead", kind: "new", archived: false },
      { key: "open_leads", label: "Open Leads", kind: "open", archived: false },
      { key: "interested", label: "Interested", kind: "open", archived: false },
    ],
  }),
}));
vi.mock("./use-pipelines", () => ({
  usePipelines: () => null,
  several: () => false,
  forgetPipelines: () => undefined,
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { ImportFlow } from "./import-flow";
import {
  columnRows,
  KEEP,
  isSerialColumn,
  looksLikePhones,
  questionsOf,
  SKIP,
  tally,
  type MatchState,
} from "./import-match";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Lead import I2 (owner's picks, 17 Nov 2026): every column in one state (I2-A),
// the phone's questions one at a time (I2-C), and what the import then sends. Made-up
// people only.
const PREVIEW: ImportPreview = {
  file_name: "expo.csv",
  headers: [
    "Sr No",
    "Customer Name",
    "Mobile No.",
    "Alternate No",
    "Status",
    "Assigned To",
    "Blank",
  ],
  rows: [
    {
      "Sr No": "1",
      "Customer Name": "Rohit Example",
      "Mobile No.": "99999 00011",
      "Alternate No": "99999 00021",
      Status: "New",
      "Assigned To": "Asha Example",
    },
    {
      "Sr No": "2",
      "Customer Name": "Kavya Sample",
      "Mobile No.": "99999 00012",
      "Alternate No": "99999 00022",
      Status: "Call back",
      "Assigned To": "Rohit P",
    },
  ],
  total_rows: 2,
  truncated: false,
  mapping: {
    name: "Customer Name",
    phone: "Mobile No.",
    stage: "Status",
    owner: "Assigned To",
  },
  with_phone: 2,
  repeats_in_file: 0,
  importable: 2,
  remembered: ["Sr No"],
  skip: ["Sr No"],
};

const CHECK: FileCheck = {
  stages: [
    { word: "New", rows: 1, stage: "new", label: "New Lead" },
    { word: "Call back", rows: 1, stage: null, label: null },
  ],
  unmatched_stage: "New Lead",
  owners: [
    {
      name: "Asha Example",
      rows: 1,
      person_id: "p1",
      person_name: "Asha Example",
    },
    { name: "Rohit P", rows: 1, person_id: null, person_name: null },
  ],
  owned_new: 1,
  columns: [],
};

const state = (more: Partial<MatchState> = {}): MatchState => ({
  preview: PREVIEW,
  mapping: PREVIEW.mapping,
  skip: ["Sr No"],
  answered: [],
  check: CHECK,
  stagePicks: {},
  ownerPicks: {},
  history: false,
  canManage: true,
  ...more,
});

it("puts every column in one state, the ones to check first", () => {
  const rows = columnRows(state());
  expect(rows.map((row) => [row.header, row.state, row.choice])).toEqual([
    ["Alternate No", "check", KEEP],
    ["Status", "check", "stage"],
    ["Assigned To", "check", "owner"],
    ["Customer Name", "matched", "name"],
    ["Mobile No.", "matched", "phone"],
    ["Sr No", "skipped", SKIP],
    ["Blank", "skipped", KEEP],
  ]);
  expect(rows.find((row) => row.header === "Sr No")?.note).toBe(
    "From your last import",
  );
  expect(tally(rows)).toEqual({ matched: 2, check: 3, skipped: 2 });
  // Answered: nothing left to check.
  const done = columnRows(
    state({
      answered: ["Alternate No"],
      stagePicks: { "Call back": "open_leads" },
      ownerPicks: { "Rohit P": "" },
    }),
  );
  expect(tally(done)).toEqual({ matched: 5, check: 0, skipped: 2 });
});

it("asks only what it can't decide, and asks for a name or phone column first", () => {
  expect(questionsOf(state()).map((item) => item.id)).toEqual([
    "column:Alternate No",
    "stage:Call back",
    "owner:Rohit P",
  ]);
  expect(questionsOf(state({ mapping: { city: "Status" } }))[0].kind).toBe(
    "need",
  );
  expect(looksLikePhones(["99999 00021", "—"])).toBe(false);
  expect(looksLikePhones(["99999 00021", "99999 00022"])).toBe(true);
  expect(looksLikePhones(["Pune", "Thane"])).toBe(false);
  // Dates are never phone numbers.
  expect(looksLikePhones(["02/11/2026", "03/11/2026"])).toBe(false);
  expect(looksLikePhones(["2026-11-02", "2026-11-03"])).toBe(false);
  expect(
    [
      "Sr No",
      "S.No.",
      "Sl No",
      "Serial number",
      "No",
      "Name",
      "Mobile No.",
    ].map(isSerialColumn),
  ).toEqual([true, true, true, true, true, false, false]);
});

let root: Root | undefined;
let host: HTMLDivElement | undefined;
const settle = async () =>
  act(async () => {
    for (let index = 0; index < 10; index += 1) await Promise.resolve();
  });
const buttons = () => [
  ...host!.querySelectorAll<HTMLButtonElement>("dialog button"),
];
const press = async (words: string) => {
  await act(async () =>
    buttons()
      .find((item) => item.textContent?.trim() === words)!
      .click(),
  );
  await settle();
};

beforeEach(() => {
  previewImport.mockResolvedValue(PREVIEW);
  checkFile.mockImplementation(
    async (
      _preview: unknown,
      _mapping: unknown,
      _side: unknown,
      _step: unknown,
      _pipeline: unknown,
      _signal: unknown,
      picks: { stages?: Record<string, string> } = {},
    ) => ({
      ...CHECK,
      stages: CHECK.stages.map((item) =>
        picks.stages?.[item.word]
          ? { ...item, stage: picks.stages[item.word] }
          : item,
      ),
    }),
  );
  commitImport.mockResolvedValue({
    created: 2,
    repeats: 0,
    skipped: 0,
    assigned: 2,
    waiting: 0,
  });
});

afterEach(async () => {
  const mounted = root;
  if (mounted) await act(async () => mounted.unmount());
  host?.remove();
  root = undefined;
  host = undefined;
  resetBackCloseForTests();
  previewImport.mockReset();
  commitImport.mockReset();
  checkFile.mockReset();
  vi.unstubAllGlobals();
});

async function mount(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: narrow,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  );
  host = document.createElement("div");
  document.body.append(host!);
  const made = createRoot(host!);
  root = made;
  await act(async () =>
    made.render(
      <ImportFlow
        open
        canManage
        onClose={() => undefined}
        onDone={() => undefined}
        pasted={"Name\tPhone\nRohit Example\t99999 00011"}
      />,
    ),
  );
  await settle();
}

it("shows the pairs on a computer, with the counts and the Advanced sheet", async () => {
  await mount(false);
  expect(host!.querySelector("[data-match-counts]")?.textContent).toBe(
    "2 matched3 to check2 not imported",
  );
  expect(
    [...host!.querySelectorAll("[data-column]")].map((row) =>
      row.getAttribute("data-column"),
    ),
  ).toEqual([
    "Alternate No",
    "Status",
    "Assigned To",
    "Customer Name",
    "Mobile No.",
    "Sr No",
    "Blank",
  ]);
  expect(host!.querySelector('[data-column="Status"]')?.textContent).toContain(
    '"Call back" isn\'t one of your stages. Choose one.',
  );
  await press("Advanced: match on your sheet");
  expect(
    host!.querySelector(
      'table[aria-label="Your file, with a label on each column"]',
    ),
  ).not.toBeNull();
  await press("Back to the list of columns");
  expect(host!.querySelector('[aria-label="Your columns"]')).not.toBeNull();
});

it("asks the phone's questions one at a time and imports with the answers", async () => {
  await mount(true);
  expect(host!.querySelector("[data-match-card]")?.textContent).toContain(
    "We matched 2 of your 7 columns",
  );
  expect(host!.textContent).toContain("Question 1 of 3");
  expect(host!.textContent).toContain("What is in 'Alternate No'?");
  await press("A second phone numberKept on the lead");
  // The answer stays on screen until Next question.
  expect(host!.textContent).toContain("What is in 'Alternate No'?");
  await press("Next question");
  expect(host!.textContent).toContain("Question 2 of 3");
  expect(host!.textContent).toContain(
    "Your 'Status' column says 'Call back'. Which stage is it?",
  );
  await press("Open Leads");
  await press("Next question");
  expect(host!.textContent).toContain("Who is 'Rohit P' in your team?");
  await press("Skip for now");
  expect(host!.textContent).toContain(
    "No questions: every column is accounted for.",
  );
  await press("Continue");
  await press("Import 2 leads");
  const [sent, mapping, , , , options] = commitImport.mock.calls[0];
  // "Sr No" isn't sent; the answers are.
  expect((sent as ImportPreview).headers).not.toContain("Sr No");
  expect((sent as ImportPreview).rows[0]).not.toHaveProperty("Sr No");
  expect(mapping).toEqual(PREVIEW.mapping);
  expect(options).toMatchObject({
    side: "cold",
    stages: { "Call back": "open_leads" },
    skipped: ["Sr No"],
    kept: ["Alternate No"],
  });
  expect(options).not.toHaveProperty("owners");
});
