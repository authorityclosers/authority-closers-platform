import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

const previewImport = vi.fn();
const commitImport = vi.fn();
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  previewImport: (...args: unknown[]) => previewImport(...args),
  commitImport: (...args: unknown[]) => commitImport(...args),
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

// Universal intake (owner, 25 Oct 2026): another CRM's export is recognised, its columns
// matched, and the preview is one line and Import: the column list waits behind "Change
// columns". Made-up people only.
let root: Root;
let host: HTMLDivElement;

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  });

async function mount(importable: number) {
  previewImport.mockResolvedValue({
    file_name: "zoho.csv",
    headers: ["First Name", "Last Name", "Mobile", "Lead Status"],
    rows: [
      {
        "First Name": "Asha",
        "Last Name": "Example",
        Mobile: "98760 72001",
        "Lead Status": "Qualified",
      },
      {
        "First Name": "Ravi",
        "Last Name": "Sample",
        Mobile: "98760 72002",
        "Lead Status": "Contacted",
      },
    ],
    total_rows: 2,
    truncated: false,
    mapping: { phone: "Mobile", stage: "Lead Status" },
    with_phone: 2,
    repeats_in_file: 0,
    known_leads: 0,
    detected: "Zoho CRM",
    importable,
  });
  commitImport.mockResolvedValue({
    created: 2,
    repeats: 0,
    skipped: 0,
    assigned: 2,
    waiting: 0,
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ImportDialog
        open
        canManage={false}
        onClose={() => undefined}
        onDone={() => undefined}
        pasted={"Name\tPhone\nAsha Example\t98760 72001"}
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

const button = (dialog: HTMLElement, text: string) =>
  Array.from(dialog.querySelectorAll("button")).find((item) =>
    item.textContent?.trim().startsWith(text),
  );

it("says which CRM's export it is and imports in one press, columns tucked away", async () => {
  const dialog = await mount(2);
  expect(dialog.textContent).toContain("Zoho CRM export.");
  expect(dialog.textContent).toContain("Columns matched: Phone, Stage");
  expect(dialog.querySelectorAll("select")).toHaveLength(0);
  await act(async () => button(dialog, "Import 2 leads")!.click());
  await settle();
  expect(commitImport).toHaveBeenCalledWith(
    expect.objectContaining({ detected: "Zoho CRM" }),
    { phone: "Mobile", stage: "Lead Status" },
    "me",
    expect.any(String),
    null,
  );
});

it("shows the columns on Change columns", async () => {
  const dialog = await mount(2);
  await act(async () => button(dialog, "Change columns")!.click());
  await settle();
  expect(dialog.querySelectorAll("select").length).toBeGreaterThan(0);
  expect(button(dialog, "Change columns")).toBeUndefined();
});

it("shows the columns when many rows make no lead", async () => {
  const dialog = await mount(1);
  expect(dialog.querySelectorAll("select").length).toBeGreaterThan(0);
  expect(button(dialog, "Change columns")).toBeUndefined();
});
