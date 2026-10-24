// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import {
  ActiveFilters,
  FilterSheet,
  filtersOn,
  type LeadFilters,
} from "./lead-filters";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Leads header (Liquid Glass, 22 Oct 2026): one Filter chip; its sheet holds the
// name or number, whose leads and the pipeline; filters that are on are chips.
const NONE: LeadFilters = { who: "team", pipeline: null, q: "" };
const PIPES = [
  { key: "main", name: "Enquiries" },
  { key: "partner", name: "Partner outreach" },
];

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
  resetBackCloseForTests();
});

const button = (label: string) =>
  [...document.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  )!;

it("counts only the filters that narrow the list", () => {
  expect(filtersOn(NONE, "team")).toBe(0);
  expect(filtersOn({ who: "mine", pipeline: null, q: " " }, "team")).toBe(1);
  expect(filtersOn({ who: "mine", pipeline: null, q: "" }, "mine")).toBe(0);
  expect(
    filtersOn({ who: "unassigned", pipeline: "partner", q: "pune" }, "team"),
  ).toBe(3);
});

it("applies a name, whose leads and a pipeline together", async () => {
  const onApply = vi.fn();
  await act(async () =>
    root.render(
      <FilterSheet
        open
        onClose={() => undefined}
        filters={NONE}
        defaultWho="team"
        canPickWho
        pipes={PIPES}
        onApply={onApply}
      />,
    ),
  );
  const input = document.querySelector<HTMLInputElement>(
    'input[type="search"]',
  )!;
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    set.call(input, "  pune ");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("Mine").click());
  await act(async () => button("Partner outreach").click());
  await act(async () => button("Show leads").click());
  expect(onApply).toHaveBeenCalledWith({
    who: "mine",
    pipeline: "partner",
    q: "pune",
  });
});

it("a seller sees no whose-leads choice, and Clear all clears", async () => {
  const onApply = vi.fn();
  await act(async () =>
    root.render(
      <FilterSheet
        open
        onClose={() => undefined}
        filters={{ who: "mine", pipeline: null, q: "pune" }}
        defaultWho="mine"
        canPickWho={false}
        pipes={[]}
        onApply={onApply}
      />,
    ),
  );
  expect(document.body.textContent).not.toContain("Whose leads");
  await act(async () => button("Clear all").click());
  expect(onApply).toHaveBeenCalledWith({
    who: "mine",
    pipeline: null,
    q: "",
    more: {},
  });
});

it("each filter that is on has its own remove", async () => {
  const onChange = vi.fn();
  const on: LeadFilters = { who: "unassigned", pipeline: "partner", q: "pune" };
  await act(async () =>
    root.render(
      <ActiveFilters
        filters={on}
        defaultWho="team"
        pipes={PIPES}
        onChange={onChange}
      />,
    ),
  );
  const labels = [...host.querySelectorAll("button")].map((item) =>
    item.getAttribute("aria-label"),
  );
  expect(labels).toEqual([
    "Remove filter “pune”",
    "Remove filter No owner",
    "Remove filter Partner outreach",
  ]);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Remove filter No owner"]',
      )!
      .click(),
  );
  expect(onChange).toHaveBeenCalledWith({ ...on, who: "team" });
});

// Owner, 24 Oct 2026: "filters and sorting both on mobile as well as PC".
it("filters by the next follow-up and the last contact, and sorts the whole list", async () => {
  const onApply = vi.fn();
  await act(async () =>
    root.render(
      <FilterSheet
        open
        onClose={() => undefined}
        filters={NONE}
        defaultWho="team"
        canPickWho
        pipes={[]}
        onApply={onApply}
      />,
    ),
  );
  await act(async () => button("Due today").click());
  await act(async () => button("Never talked").click());
  await act(async () => button("Name").click());
  await act(async () => button("Show leads").click());
  expect(onApply).toHaveBeenCalledWith({
    ...NONE,
    more: { due: "today", contact: "never", sort: "name", order: null },
  });
  expect(
    filtersOn({ ...NONE, more: { due: "today", sort: "name" } }, "team"),
  ).toBe(1);
});

it("the sort and the new filters show as chips that remove themselves", async () => {
  const onChange = vi.fn();
  const on: LeadFilters = {
    ...NONE,
    more: { due: "late", source: "csv", sort: "name", order: "desc" },
  };
  await act(async () =>
    root.render(
      <ActiveFilters
        filters={on}
        defaultWho="team"
        pipes={PIPES}
        onChange={onChange}
      />,
    ),
  );
  const labels = [...host.querySelectorAll("button")].map((item) =>
    item.getAttribute("aria-label"),
  );
  expect(labels).toEqual([
    "Remove filter Late",
    "Remove filter File upload",
    "Remove filter By name, reversed",
  ]);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Remove filter Late"]')!
      .click(),
  );
  expect(onChange).toHaveBeenCalledWith({
    ...on,
    more: { ...on.more, due: null },
  });
});
