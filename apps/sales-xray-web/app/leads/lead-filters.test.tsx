// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import {
  ActiveFilters,
  FilterSheet,
  filterNames,
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

const openChoices = (label: string) =>
  act(async () => {
    [
      ...document.querySelectorAll<HTMLElement>(
        'button[aria-haspopup="listbox"]',
      ),
    ]
      .find((item) => item.textContent?.startsWith(label))!
      .click();
  });

const option = (label: string) =>
  [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
    (item) => item.textContent?.trim() === label,
  )!;

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

// Robot J181 (2 Nov 2026): an empty filtered list names the filters on, in their
// chips' words; a sort hides nothing, and Follow-ups' own split isn't a filter.
it("names the filters that narrow the list, in their chips' words", () => {
  expect(
    filterNames(
      {
        who: "mine",
        pipeline: null,
        q: "",
        more: {
          source: "manual",
          created: "month",
          when: "upcoming",
          sort: "name",
        },
      },
      "team",
    ),
  ).toEqual([
    "Mine",
    "Follow-up upcoming",
    "Came in this month",
    "Added by hand",
  ]);
  expect(
    filterNames(
      {
        who: "team",
        pipeline: null,
        q: "",
        more: { view: "follow_ups", when: "today" },
      },
      "team",
    ),
  ).toEqual([]);
});

it("applies whose leads and a pipeline together", async () => {
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
  // Search is on the Leads page itself (Dipak's handoff, 31 Oct 2026).
  expect(document.querySelector('input[type="search"]')).toBeNull();
  await openChoices("Whose leads");
  await act(async () => option("Mine").click());
  await openChoices("Pipeline");
  await act(async () => option("Partner outreach").click());
  await act(async () => button("Show Results").click());
  expect(onApply).toHaveBeenCalledWith({
    who: "mine",
    pipeline: "partner",
    q: "",
  });
});

it("a seller sees no whose-leads choice, and Clear Filters clears", async () => {
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
  await act(async () => button("Clear Filters").click());
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

// Owner, 24 Oct 2026: "filters and sorting both on mobile as well as PC"; Dipak's
// handoff, 31 Oct 2026 (items 50-53): lead source, date and follow-up.
it("filters by source, date and follow-up, and sorts the whole list", async () => {
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
  await openChoices("Lead source");
  await act(async () => option("File upload").click());
  await openChoices("Date");
  await act(async () => option("Came in today").click());
  await openChoices("Follow-up");
  await act(async () => option("Overdue").click());
  await openChoices("Sort by");
  await act(async () => option("Name").click());
  await act(async () => button("Show Results").click());
  expect(onApply).toHaveBeenCalledWith({
    ...NONE,
    more: {
      source: "csv",
      created: "today",
      when: "overdue",
      due: null,
      sort: "name",
      order: null,
    },
  });
  expect(
    filtersOn({ ...NONE, more: { due: "today", sort: "name" } }, "team"),
  ).toBe(1);
  // In Follow-ups the split is the view's own tabs, not a filter.
  expect(filtersOn({ ...NONE, more: { when: "today" } }, "team")).toBe(1);
  expect(
    filtersOn({ ...NONE, more: { view: "follow_ups", when: "today" } }, "team"),
  ).toBe(0);
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

it("asks for the pipeline first, then whose leads, then source, date and follow-up", async () => {
  await act(async () =>
    root.render(
      <FilterSheet
        open
        onClose={() => undefined}
        filters={NONE}
        defaultWho="team"
        canPickWho
        pipes={PIPES}
        onApply={() => undefined}
      />,
    ),
  );
  // Pipeline first (orchestrator, 25 Oct 2026: the most important filter for AC).
  const fields = [...document.querySelectorAll("form > *")].map(
    (field) => field.textContent ?? "",
  );
  expect(fields[0]).toContain("Pipeline");
  expect(fields[1]).toContain("Whose leads");
  expect(fields).toHaveLength(6);
  expect(fields[2]).toContain("Lead source");
  expect(fields[3]).toContain("Date");
  expect(fields[4]).toContain("Follow-up");
  expect(fields[5]).toContain("Sort by");
});

it("sorts oldest first: the newest-first order, reversed", async () => {
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
  await openChoices("Sort by");
  expect(option("Newest first")).toBeTruthy();
  await act(async () => option("Oldest first").click());
  await act(async () => button("Show Results").click());
  expect(onApply).toHaveBeenCalledWith({
    who: "team",
    pipeline: null,
    q: "",
    more: { sort: "created", order: "asc" },
  });
});
