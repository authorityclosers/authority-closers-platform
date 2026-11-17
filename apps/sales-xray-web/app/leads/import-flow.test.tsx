import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

const previewImport = vi.fn();
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  previewImport: (...args: unknown[]) => previewImport(...args),
  readTeam: async () => ({ reps: [] }),
  readImports: async () => ({ imports: [] }),
  checkFile: async () => ({
    stages: [],
    unmatched_stage: null,
    owners: [],
    owned_new: 0,
    columns: [],
  }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

vi.mock("./use-pipelines", () => ({
  usePipelines: () => null,
  several: () => false,
  forgetPipelines: () => undefined,
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { fileSize, ImportFlow, OVER_LIMIT, sheetLine } from "./import-flow";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Lead import I1 (owner's picks, 17 Nov 2026): the file step as a full-page
// workspace (I1-A) and, for an Excel file with several sheets, "Which sheet has
// your leads?" with its first rows (I1-B). Made-up people only.
let root: Root;
let host: HTMLDivElement;

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });

const LEADS = {
  file_name: "expo-leads.xlsx",
  headers: ["Customer Name", "Mobile No.", "Email ID", "City/Town"],
  rows: [
    {
      "Customer Name": "Asha Example",
      "Mobile No.": "98760 75001",
      "City/Town": "Pune",
    },
    { "Customer Name": "Ravi Sample", "Mobile No.": "98760 75002" },
  ],
  total_rows: 2,
  truncated: false,
  mapping: { name: "Customer Name", phone: "Mobile No." },
  with_phone: 2,
  repeats_in_file: 0,
  importable: 2,
  sheets: [
    { name: "Summary", rows: 0, columns: 0 },
    { name: "Leads", rows: 2, columns: 4 },
    { name: "Old", rows: 1, columns: 2 },
  ],
  sheet: "Leads",
};

async function mount() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ImportFlow
        open
        canManage
        onClose={() => undefined}
        onDone={() => undefined}
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
});

const buttons = (dialog: HTMLElement) => [...dialog.querySelectorAll("button")];
const current = (dialog: HTMLElement) =>
  dialog.querySelector('[aria-label="Import steps"] [aria-current="step"]')
    ?.textContent;

async function choose(dialog: HTMLElement, file: File) {
  const input = dialog.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () =>
    input.dispatchEvent(new Event("change", { bubbles: true })),
  );
  await settle();
}

it("opens on the file step with the drop area, the other ways and a sample", async () => {
  const dialog = await mount();
  expect(dialog.getAttribute("data-import-flow")).toBe("");
  expect(current(dialog)).toBe("1File");
  expect(
    [...dialog.querySelectorAll('[aria-label="Import steps"] li')].map(
      (item) => item.textContent,
    ),
  ).toEqual(["1File", "2Match columns", "3Check", "4Assign"]);
  expect(dialog.textContent).toContain("Bring in your leads");
  expect(dialog.textContent).toContain("Drop your file here");
  expect(dialog.textContent).toContain("Choose an Excel or CSV file");
  const ways = buttons(dialog).map(
    (item) => item.querySelector("strong")?.parentElement?.textContent,
  );
  expect(ways).toContain(
    "Facebook lead form fileUpload the CSV you downloaded",
  );
  expect(ways).toContain("Paste rowsFrom a sheet, a chat or ChatGPT");
  // Google isn't connected here: the row says to connect it first.
  expect(dialog.textContent).toContain("Connect Google Sheets first");
  expect(
    [...dialog.querySelectorAll("a")].find(
      (link) => link.textContent === "Download a sample file",
    ),
  ).toBeDefined();
  // No paste box until Paste rows is chosen.
  expect(dialog.querySelector('textarea[aria-label="Paste rows"]')).toBeNull();
});

it("asks which sheet has the leads, shows its first rows and reads another sheet", async () => {
  previewImport.mockResolvedValueOnce(LEADS);
  const dialog = await mount();
  const file = new File(["xlsx"], "expo-leads.xlsx");
  await choose(dialog, file);
  expect(previewImport).toHaveBeenCalledWith(file, undefined);
  // Still on File: the sheets first.
  expect(current(dialog)).toBe("1File");
  expect(dialog.textContent).toContain("Which sheet has your leads?");
  const sheets = [...dialog.querySelectorAll('[role="radio"]')];
  expect(sheets.map((item) => item.textContent)).toEqual([
    "Summary · no leads",
    "Leads · 2 rows · 4 columns",
    "Old · 1 row · 2 columns",
  ]);
  expect(sheets[1].getAttribute("aria-checked")).toBe("true");
  expect(dialog.querySelector("[data-import-found]")?.textContent).toContain(
    "Found 2 rows · 4 columns.",
  );
  expect(
    [...dialog.querySelectorAll("thead th")].map((cell) => cell.textContent),
  ).toEqual(LEADS.headers);
  expect(dialog.textContent).toContain("+ 2 more columns");

  previewImport.mockResolvedValueOnce({
    ...LEADS,
    headers: ["Name", "Phone"],
    rows: [{ Name: "Meera Demo", Phone: "98760 75003" }],
    total_rows: 1,
    mapping: { name: "Name", phone: "Phone" },
    importable: 1,
    sheet: "Old",
  });
  await act(async () => (sheets[2] as HTMLButtonElement).click());
  await settle();
  expect(previewImport).toHaveBeenLastCalledWith(file, "Old");
  expect(
    dialog.querySelectorAll('[role="radio"]')[2].getAttribute("aria-checked"),
  ).toBe("true");

  // Match columns (I2-A): every file goes through it.
  await act(async () =>
    buttons(dialog)
      .find((item) => item.textContent === "Match columns")!
      .click(),
  );
  expect(current(dialog)).toBe("2Match columns");
  expect(dialog.textContent).toContain("expo-leads.xlsx (Old): 1 rows");
});

it("opens Match columns straight away for a file with one sheet", async () => {
  previewImport.mockResolvedValueOnce({
    ...LEADS,
    mapping: { city: "City/Town" },
    importable: 0,
    sheets: [],
    sheet: null,
  });
  const dialog = await mount();
  await choose(dialog, new File(["csv"], "list.csv"));
  expect(current(dialog)).toBe("2Match columns");
  expect(dialog.querySelector('[role="radiogroup"]')).toBeNull();
});

it("says a file over 2,000 rows comes in only in part", async () => {
  previewImport.mockResolvedValueOnce({ ...LEADS, truncated: true });
  const dialog = await mount();
  await choose(dialog, new File(["xlsx"], "big.xlsx"));
  expect(dialog.querySelector("[data-import-over]")?.textContent).toBe(
    OVER_LIMIT,
  );
});

it("says sizes and sheets as people read them", () => {
  expect(fileSize(900)).toBe("900 B");
  expect(fileSize(48 * 1024)).toBe("48 KB");
  expect(fileSize(1.5 * 1024 * 1024)).toBe("1.5 MB");
  expect(sheetLine({ rows: 0, columns: 0 })).toBe("no leads");
  expect(sheetLine({ rows: 1, columns: 11 })).toBe("1 row · 11 columns");
  expect(sheetLine({ rows: 2400, columns: 3 })).toBe("2,400 rows · 3 columns");
});
