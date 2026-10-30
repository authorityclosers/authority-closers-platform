// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LeadsMenu, type LeadsMenuItem } from "./leads-menu";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
const entries = [
  ["share", "Share out leads"],
  ["team", "Lead rules"],
  ["sources", "Lead sources"],
  ["numbers", "Pipeline numbers"],
  ["stages", "Lead stages"],
  ["import", "Import leads"],
  ["test", "Test leads"],
];
const items = (): LeadsMenuItem[] =>
  entries.map(([key, label]) => ({
    key,
    label,
    note: "A short hint",
    onPick: vi.fn(),
  }));
beforeEach(() => {
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = true;
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.open = false;
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it("groups every existing destination in job order with an icon and its original action", async () => {
  const rows = items();
  await act(async () =>
    root.render(<LeadsMenu open onClose={() => {}} items={rows} />),
  );
  expect(
    Array.from(host.querySelectorAll("h3"), (el) => el.textContent),
  ).toEqual(["Set up leads", "Manage leads"]);
  const buttons = Array.from(
    host.querySelectorAll<HTMLButtonElement>("li > button"),
  );
  const order = [
    "sources",
    "stages",
    "team",
    "share",
    "import",
    "numbers",
    "test",
  ];
  expect(buttons).toHaveLength(7);
  for (const [index, key] of order.entries()) {
    const item = rows.find((row) => row.key === key)!;
    expect(buttons[index].querySelector("strong")?.textContent).toBe(
      item.label,
    );
    expect(
      buttons[index].querySelector('span[aria-hidden="true"] svg'),
    ).not.toBeNull();
    expect(buttons[index].querySelector("small")?.textContent).toBe(item.note);
    await act(async () => buttons[index].click());
    expect(item.onPick).toHaveBeenCalledOnce();
  }
});

it("keeps permission-filtered rows absent and omits empty groups", async () => {
  const rows = items().filter((item) =>
    ["stages", "numbers", "import"].includes(item.key),
  );
  await act(async () =>
    root.render(<LeadsMenu open onClose={() => {}} items={rows} />),
  );
  expect(
    Array.from(host.querySelectorAll("h3"), (el) => el.textContent),
  ).toEqual(["Set up leads", "Manage leads"]);
  expect(host.querySelectorAll("li")).toHaveLength(3);
  for (const label of [
    "Share out leads",
    "Lead rules",
    "Lead sources",
    "Test leads",
  ])
    expect(host.textContent).not.toContain(label);
});

it("keeps Notes, off the Leads strip, first in the menu, for a seller too", async () => {
  // Owner and Dipak, 30 Oct 2026: no Now and no More on Leads.
  const notes = {
    key: "notes",
    label: "Notes",
    note: "Search",
    onPick: vi.fn(),
  };
  await act(async () =>
    root.render(
      <LeadsMenu open onClose={() => {}} items={[...items(), notes]} />,
    ),
  );
  expect(
    Array.from(host.querySelectorAll("h3"), (el) => el.textContent),
  ).toEqual(["Your work", "Set up leads", "Manage leads"]);
  await act(async () =>
    root.render(<LeadsMenu open onClose={() => {}} items={[notes]} />),
  );
  const only = Array.from(
    host.querySelectorAll<HTMLButtonElement>("li > button"),
  );
  expect(only.map((button) => button.textContent)).toEqual([
    expect.stringContaining("Notes"),
  ]);
  await act(async () => only[0].click());
  expect(notes.onPick).toHaveBeenCalled();
});
