// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  request: vi.fn(),
  readLead: vi.fn(),
  run: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("../notice-center", () => ({ notify: calls.notify }));
vi.mock("./leads-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./leads-client")>()),
  deskRequest: calls.request,
  readLead: calls.readLead,
}));
vi.mock("./manage-bar", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./manage-bar")>()),
  runWithUndo: calls.run,
}));

import type { LeadDetail, LeadPage, LeadRow } from "./leads-client";
import { purgeDay, shelfNote } from "./shelf-client";
import { ShelfView } from "./shelf-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const row = (id: string, name: string, extra: Partial<LeadRow>) =>
  ({
    lead_id: id,
    name,
    stage_label: "Follow-up",
    owner_name: "meera fictional",
    source_label: "Meta",
    ...extra,
  }) as LeadRow;

const BIN: LeadPage = {
  leads: [
    row("lead-1", "asha fictional", { binned_at: "2026-11-10T06:00:00Z" }),
    row("lead-2", "ravi sample", { binned_at: "2026-11-12T06:00:00Z" }),
  ],
  total: 2,
  next_offset: null,
};
const ARCHIVED: LeadPage = {
  leads: [row("lead-3", "kiran test", { archived_at: "2026-11-15T06:00:00Z" })],
  total: 1,
  next_offset: null,
};

let container: HTMLDivElement;
let root: Root;
const opened: string[] = [];
const shelves: string[] = [];

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  opened.length = 0;
  shelves.length = 0;
  calls.request.mockImplementation((path: string) =>
    Promise.resolve(path.includes("shelf=bin") ? BIN : ARCHIVED),
  );
  calls.run.mockResolvedValue({ job_id: "job-1", changed: 1 });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

async function show(shelf: "archived" | "bin", canBin = true) {
  await act(async () => {
    root.render(
      <ShelfView
        shelf={shelf}
        canBin={canBin}
        onShelf={(next) => shelves.push(next)}
        onOpen={(id) => opened.push(id)}
      />,
    );
  });
}

const buttons = (label: string) =>
  Array.from(document.querySelectorAll("button")).filter(
    (item) => item.textContent?.trim() === label,
  );

it("says the day the Bin deletes a lead for good", () => {
  expect(purgeDay("2026-11-10T06:00:00Z").toISOString()).toBe(
    "2026-12-10T06:00:00.000Z",
  );
  expect(shelfNote("bin", { binned_at: "2026-11-10T06:00:00Z" })).toBe(
    "Deleted for good on 10 Dec 2026",
  );
  expect(shelfNote("archived", { archived_at: "2026-11-15T06:00:00Z" })).toBe(
    "Archived on 15 Nov 2026",
  );
});

it("lists the Bin with each lead's last day and restores one", async () => {
  await show("bin");
  expect(calls.request).toHaveBeenCalledWith(
    "/leads?scope=team&shelf=bin",
    expect.anything(),
  );
  expect(container.textContent).toContain("Deleted for good on 10 Dec 2026");
  expect(container.textContent).toContain("Deleted for good on 12 Dec 2026");
  await act(async () => buttons("Restore")[0]!.click());
  expect(calls.run).toHaveBeenCalledWith(
    { lead_ids: ["lead-1"], action: "restore_bin" },
    expect.any(String),
  );
  // The list is read again after the restore.
  expect(calls.request).toHaveBeenCalledTimes(2);
});

it("restores the ticked leads as one bulk job", async () => {
  await show("archived");
  const tick = container.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )!;
  await act(async () => tick.click());
  expect(container.textContent).toContain("1 chosen");
  await act(async () => buttons("Restore 1")[0]!.click());
  expect(calls.run).toHaveBeenCalledWith(
    { lead_ids: ["lead-3"], action: "restore_archive" },
    expect.any(String),
  );
});

it("opens an archived lead on Leads", async () => {
  await show("archived");
  await act(async () =>
    container.querySelector<HTMLButtonElement>("[data-lead-row]")!.click(),
  );
  expect(opened).toEqual(["lead-3"]);
});

it("opens a lead in the Bin to read only, with Restore", async () => {
  calls.readLead.mockResolvedValue({
    lead: BIN.leads[0],
    phone: "+91 90000 00000",
    email: null,
    fields: [],
    events: [{ at: "2026-11-09T06:00:00Z", note: "Wants a quote" }],
  } as unknown as LeadDetail);
  await show("bin");
  await act(async () =>
    container.querySelector<HTMLButtonElement>("[data-lead-row]")!.click(),
  );
  expect(opened).toEqual([]);
  expect(calls.readLead).toHaveBeenCalledWith("lead-1", expect.anything());
  expect(document.body.textContent).toContain("Read only");
  expect(document.body.textContent).toContain("Wants a quote");
  await act(async () => buttons("Restore to Leads")[0]!.click());
  expect(calls.run).toHaveBeenCalledWith(
    { lead_ids: ["lead-1"], action: "restore_bin" },
    expect.any(String),
  );
});

it("shows the Bin's tab only to owners and admins", async () => {
  await show("archived", false);
  expect(buttons("Bin")).toHaveLength(0);
  await show("archived", true);
  await act(async () => buttons("Bin")[0]!.click());
  expect(shelves).toEqual(["bin"]);
});
