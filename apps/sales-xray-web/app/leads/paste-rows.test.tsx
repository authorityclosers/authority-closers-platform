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

import { resetBackCloseForTests } from "../ui/back-close";
import { ImportDialog } from "./capture-dialogs";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Leads pasted as text (owner P0, 23 Oct 2026): the import reads rows pasted
// into its box, or into the list's quick add, as it reads a file.
let root: Root;
let host: HTMLDivElement;

async function mount(pasted: string | null = null) {
  previewImport.mockImplementation(async (file: File) => ({
    file_name: file.name,
    headers: ["Name", "Phone"],
    rows: [
      { Name: "Asha Example", Phone: "98765 43210" },
      { Name: "Ravi Sample", Phone: "91234 56789" },
    ],
    total_rows: 2,
    truncated: false,
    mapping: { name: "Name", phone: "Phone" },
    with_phone: 2,
    repeats_in_file: 0,
  }));
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
        pasted={pasted}
      />,
    ),
  );
  await settle();
  return host.querySelector("dialog")!;
}

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  });

const paste = async (target: HTMLElement, text: string) => {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", {
    value: { getData: () => text },
  });
  await act(async () => target.dispatchEvent(event));
  await settle();
};

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  previewImport.mockReset();
  commitImport.mockReset();
});

it("reads rows pasted into quick add as it opens, and adds them all", async () => {
  const dialog = await mount(
    "Name\tPhone\nAsha Example\t98765 43210\nRavi Sample\t91234 56789\n",
  );
  expect(previewImport).toHaveBeenCalledTimes(1);
  const file = previewImport.mock.calls[0][0] as File;
  expect(file.name).toBe("Pasted leads.csv");
  expect(await file.text()).toBe(
    "Name,Phone\nAsha Example,98765 43210\nRavi Sample,91234 56789",
  );
  expect(dialog.textContent).toContain("Pasted: 2 rows");
  const add = Array.from(dialog.querySelectorAll("button")).find(
    (button) => button.textContent?.trim() === "Import 2 leads",
  )!;
  await act(async () => add.click());
  await settle();
  expect(commitImport).toHaveBeenCalledWith(
    expect.objectContaining({ file_name: "Pasted leads.csv" }),
    { name: "Name", phone: "Phone" },
    "me",
    expect.any(String),
    null,
  );
  expect(dialog.textContent).toContain("New leads");
});

it("reads rows pasted into its box, and says when the text holds none", async () => {
  const dialog = await mount();
  const box = dialog.querySelector<HTMLTextAreaElement>(
    'textarea[aria-label="Paste rows"]',
  )!;
  await paste(box, "Name\tPhone\n");
  expect(previewImport).not.toHaveBeenCalled();
  expect(dialog.querySelector('[role="alert"]')?.textContent).toContain(
    "There are no rows in that",
  );
  await paste(
    box,
    "| Name | Phone |\n|---|---|\n| Asha Example | 9876543210 |",
  );
  expect(previewImport).toHaveBeenCalledTimes(1);
  expect(await (previewImport.mock.calls[0][0] as File).text()).toBe(
    "Name,Phone\nAsha Example,9876543210",
  );
});
