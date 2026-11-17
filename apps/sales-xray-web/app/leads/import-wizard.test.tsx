import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

const previewImport = vi.fn();
const commitImport = vi.fn();
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  previewImport: (...args: unknown[]) => previewImport(...args),
  commitImport: (...args: unknown[]) => commitImport(...args),
  checkFile: async () => ({
    stages: [],
    unmatched_stage: null,
    owners: [],
    owned_new: 0,
    columns: [],
  }),
  readTeam: async () => ({
    // Sellers who take new leads, and an owner who doesn't (owner, 2 Nov 2026).
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
        person_id: "p0",
        name: "Owner Example",
        open_leads: 0,
        max_open: null,
        available: false,
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

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown 5 (1 Nov 2026): the import in four steps, File, Match columns,
// Check and Assign, with the check before anything is written. A file
// whose columns didn't all match starts on Columns, each with three of its
// values. Made-up people only.
let root: Root;
let host: HTMLDivElement;

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });

const ROWS = [
  { Customer: "Asha Example", Mobile: "98760 75001", Town: "Pune" },
  { Customer: "Ravi Sample", Mobile: "call after 6", Town: "" },
  { Customer: "Meera Demo", Mobile: "98760 75003", Town: "Nashik" },
  { Customer: "Kiran Sample", Mobile: "98760 75009", Town: "Nagpur" },
  { Customer: "Neha Demo", Mobile: "98760 75010", Town: "Thane" },
];

async function mount() {
  previewImport.mockResolvedValue({
    file_name: "fictional-list.csv",
    headers: ["Customer", "Mobile", "Town"],
    rows: ROWS,
    total_rows: 5,
    truncated: false,
    // The name column wasn't matched: Columns first.
    mapping: { phone: "Mobile", city: "Town" },
    with_phone: 4,
    repeats_in_file: 0,
    known_leads: 1,
    importable: 3,
    bad_numbers: 1,
  });
  commitImport.mockResolvedValue({
    created: 3,
    repeats: 1,
    skipped: 1,
    assigned: 3,
    waiting: 0,
    updated: 1,
    skipped_rows: [{ row: 1, reason: "Number can't be read" }],
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
        pasted={"Customer\tMobile\nAsha Example\t98760 75001"}
      />,
    ),
  );
  await settle();
  return host.querySelector("dialog")!;
}

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  previewImport.mockReset();
  commitImport.mockReset();
});

const button = (dialog: HTMLElement, words: string) =>
  Array.from(dialog.querySelectorAll("button")).find(
    (item) => item.textContent?.trim() === words,
  );
const current = (dialog: HTMLElement) =>
  dialog.querySelector('[aria-label="Import steps"] [aria-current="step"]')
    ?.textContent;

it("walks File, Match columns, Check and Assign, and imports with the choices made", async () => {
  const dialog = await mount();
  expect(current(dialog)).toBe("2Match columns");
  // Every column of the file with three of its values (I2-A).
  expect(dialog.querySelector('[data-samples="Mobile"]')?.textContent).toBe(
    "98760 75001 · call after 6 · 98760 75003",
  );
  expect(dialog.querySelector('[data-samples="Town"]')?.textContent).toBe(
    "Pune · Nashik · Nagpur",
  );
  // "Customer" wasn't matched: it stays on the lead under its own name.
  expect(
    dialog.querySelector(
      '[data-column="Customer"] button[aria-haspopup="listbox"]',
    )?.textContent,
  ).toContain("Keep on the lead");

  await act(async () => button(dialog, "Continue to check leads")!.click());
  await settle();
  expect(current(dialog)).toBe("3Check");
  const counts = Object.fromEntries(
    [...dialog.querySelectorAll("[data-check]")].map((line) => [
      line.getAttribute("data-check"),
      line.querySelector("dd")?.textContent,
    ]),
  );
  expect(counts).toEqual({ new: "2", known: "1", bad: "1", blank: "1" });
  // An even split by default, said in a line.
  expect(dialog.querySelector("[data-import-who]")?.textContent).toContain(
    "About 2 new leads: Asha Example 1 · Ravi Sample 1.",
  );
  await act(async () => button(dialog, "Fill blanks")!.click());
  expect(dialog.querySelector('[data-duplicates="fill"]')).not.toBeNull();

  await act(async () => button(dialog, "Change")!.click());
  expect(current(dialog)).toBe("4Assign");
  // Shared between the sellers only: the owner isn't one.
  expect(dialog.textContent).not.toContain("Owner Example");
  await act(async () => button(dialog, "Back")!.click());
  expect(current(dialog)).toBe("3Check");

  // Import is on Assign (I4-A), beside "When you import".
  await act(async () => button(dialog, "Continue to assign")!.click());
  await settle();
  expect(dialog.querySelector('[data-summary="new"]')?.textContent).toContain(
    "2 new leads",
  );
  await act(async () => button(dialog, "Import 2 leads")!.click());
  await settle();
  expect(commitImport).toHaveBeenCalledWith(
    expect.objectContaining({ file_name: "fictional-list.csv" }),
    { phone: "Mobile", city: "Town" },
    "people",
    expect.any(String),
    null,
    {
      side: "cold",
      shares: [
        { person_id: "p1", count: 1 },
        { person_id: "p2", count: 1 },
      ],
      duplicates: "fill",
    },
  );
  // The receipt (I4-B): what was filled in, what wasn't imported, the rows as a file.
  const receipt = dialog.querySelector("[data-import-receipt]")!;
  expect(receipt.querySelector("h3")?.textContent).toBe("3 leads imported");
  expect(receipt.textContent).toContain("Details filled in· 1 lead");
  expect(receipt.textContent).toContain("2 rows not imported");
  expect(
    [...dialog.querySelectorAll("a")].find((link) =>
      link.textContent?.startsWith("Download rows not added"),
    )?.textContent,
  ).toBe("Download rows not added (1, with reason)");
  expect(dialog.querySelector('[aria-label="Import steps"]')).toBeNull();
});

it("goes back from Match columns to choose another file", async () => {
  const dialog = await mount();
  await act(async () => button(dialog, "Back")!.click());
  expect(current(dialog)).toBe("1File");
  expect(
    dialog.querySelector('textarea[aria-label="Paste rows"]'),
  ).not.toBeNull();
  // Cold Leads unless picked otherwise, on the first step.
  expect(dialog.textContent).toContain("Where should these leads go?");
});
