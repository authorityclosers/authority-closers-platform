import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import type { FileCheck } from "./leads-client";

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
        open_leads: 0,
        max_open: null,
        available: true,
      },
      {
        person_id: "p2",
        name: "Ravi Sample",
        open_leads: 0,
        max_open: null,
        available: true,
      },
      {
        person_id: "p3",
        name: "Farah Shaikh",
        open_leads: 0,
        max_open: null,
        available: true,
      },
    ],
  }),
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

vi.mock("./use-pipelines", () => ({
  usePipelines: () => null,
  several: () => false,
  forgetPipelines: () => undefined,
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { ImportDialog } from "./capture-dialogs";
import { FileCheckLines } from "./import-file-check";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The owner's import study (16 Nov 2026): the file's own owners win over
// "Share between my sellers", a status that is no stage here is said and kept,
// and every column is accounted for. Made-up people only.
let root: Root;
let host: HTMLDivElement;

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });

const CHECK: FileCheck = {
  stages: [
    { word: "Call back", rows: 2, stage: "open_leads", label: "Open Leads" },
    { word: "Will think", rows: 1, stage: null, label: null },
  ],
  unmatched_stage: "Unworked",
  owners: [
    { name: "Farah", rows: 2, person_id: "p3", person_name: "Farah Shaikh" },
    { name: "Nobody Known", rows: 1, person_id: null, person_name: null },
  ],
  owned_new: 2,
  columns: [
    { header: "Sr No", fate: "kept", field: null },
    { header: "Customer Name", fate: "matched", field: "name" },
    { header: "Mobile No.", fate: "matched", field: "phone" },
    { header: "City/Town", fate: "matched", field: "city" },
    { header: "Status", fate: "matched", field: "stage" },
    { header: "Assigned To", fate: "matched", field: "owner" },
    { header: "Remarks", fate: "kept", field: null },
    { header: "lead_id", fate: "not_imported", field: null },
    { header: "Blank", fate: "empty", field: null },
  ],
};

const ROWS = [
  {
    "Customer Name": "Rahul Kumar Example",
    "Mobile No.": "98760 74001",
    Status: "Call back",
    "Assigned To": "Farah",
  },
  {
    "Customer Name": "Pooja Sharma Sample",
    "Mobile No.": "98760 74002",
    Status: "Will think",
  },
  {
    "Customer Name": "Amit Verma Demo",
    "Mobile No.": "98760 74003",
    Status: "Call back",
    "Assigned To": "Nobody Known",
  },
  {
    "Customer Name": "Sneha Patil Fresh",
    "Mobile No.": "98760 74004",
    "Assigned To": "Farah",
  },
];

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  previewImport.mockReset();
  commitImport.mockReset();
  checkFile.mockReset();
});

it("says each stage word, the owners and every column's fate", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <FileCheckLines
        state={{ check: CHECK, error: null }}
        stageColumn="Status"
      />,
    ),
  );
  const stages = [...host.querySelectorAll('[data-file-check="stages"] dt')];
  expect(stages.map((line) => line.textContent)).toEqual([
    "Call back → Open Leads",
    "Will think → no stage by that name: starts in Unworked",
  ]);
  expect(host.querySelector('[data-file-check="unplaced"]')?.textContent).toBe(
    "1 lead's stage isn't one of your stages: the file's word stays on each lead, under Status.",
  );
  expect(host.querySelector('[data-file-check="owners"]')?.textContent).toBe(
    "Owners from your file keep their leads: Farah Shaikh 2. Nobody on your team called Nobody Known: those rows go the way you pick under Assign.",
  );
  expect(host.querySelector('[data-file-check="columns"]')?.textContent).toBe(
    "Your 9 columns: 5 matched · 2 kept on each lead as details (Sr No, Remarks) · 1 empty, so not imported (Blank) · 1 not imported: another app's ids (lead_id).",
  );
});

it("shares only the leads without an owner in the file", async () => {
  previewImport.mockResolvedValue({
    file_name: "fictional-ns.csv",
    headers: ["Customer Name", "Mobile No.", "Status", "Assigned To"],
    rows: ROWS,
    total_rows: 4,
    truncated: false,
    mapping: {
      name: "Customer Name",
      phone: "Mobile No.",
      stage: "Status",
      owner: "Assigned To",
    },
    with_phone: 4,
    repeats_in_file: 0,
    known_leads: 0,
    importable: 4,
    bad_numbers: 0,
  });
  let answer: (value: FileCheck) => void = () => undefined;
  checkFile.mockImplementation(
    () => new Promise<FileCheck>((resolve) => (answer = resolve)),
  );
  commitImport.mockResolvedValue({
    created: 4,
    repeats: 0,
    skipped: 0,
    assigned: 4,
    waiting: 0,
    owned: 2,
    unmatched_stages: ["Will think"],
    skipped_rows: [],
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ImportDialog
        open
        canManage
        onClose={() => undefined}
        onDone={() => undefined}
        pasted={"Customer Name\tMobile No.\nRahul Kumar Example\t98760 74001"}
      />,
    ),
  );
  await settle();
  const dialog = host.querySelector("dialog")!;
  // Match columns first (I2-A), then Check.
  await act(async () =>
    Array.from(dialog.querySelectorAll("button"))
      .find((item) => item.textContent === "Continue to check leads")!
      .click(),
  );
  await settle();
  const pressable = (words: string) =>
    Array.from(dialog.querySelectorAll("button")).find((item) =>
      item.textContent?.trim().startsWith(words),
    )!;
  // The file is still being checked: no going on to Assign, no Import yet.
  expect(pressable("Continue to assign").disabled).toBe(true);
  expect(checkFile).toHaveBeenCalledWith(
    expect.objectContaining({ file_name: "fictional-ns.csv" }),
    expect.objectContaining({ owner: "Assigned To" }),
    "cold",
    "",
    null,
    expect.anything(),
    { stages: {}, owners: {} },
  );
  await act(async () => answer(CHECK));
  await settle();
  expect(dialog.querySelector("[data-import-who]")?.textContent).toContain(
    "About 4 new leads: 2 keep their owner from your file; the other 2: Asha Example 1 · Ravi Sample 1.",
  );
  await act(async () => pressable("Continue to assign").click());
  await settle();
  expect(dialog.querySelector("[data-file-owners]")?.textContent).toContain(
    "Owners from your file keep their leads",
  );
  await act(async () => pressable("Import 4").click());
  await settle();
  // Share between my sellers covers only the two rows without an owner.
  expect(commitImport.mock.calls[0][5]).toMatchObject({
    shares: [
      { person_id: "p1", count: 1 },
      { person_id: "p2", count: 1 },
    ],
  });
  expect(dialog.textContent).toContain(
    "No stage called Will think: those leads start in Unworked, and keep the file's word on the lead.",
  );
});
