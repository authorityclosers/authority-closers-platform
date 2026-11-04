// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { readLeads, type LeadRow } from "./leads-client";
import { ListView } from "./list-view";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: () => undefined,
}));
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  readLeads: vi.fn(),
}));
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const row = (n: number): LeadRow => ({
  lead_id: `fictional-${n}`,
  revision: 1,
  name: `Fictional prospect ${n}`,
  company: null,
  city: null,
  language: null,
  interest: null,
  phone_last4: null,
  stage: "new",
  stage_label: "New lead",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-28T00:00:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  localStorage.clear();
  vi.mocked(readLeads).mockResolvedValue({
    leads: Array.from({ length: 30 }, (_, n) => row(n)),
    total: 30,
    next_offset: null,
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  document.documentElement.style.fontSize = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// As a browser's: it tells about each watched row once watched, and nothing
// more once disconnected until it watches again.
class Watch {
  private readonly targets = new Set<Element>();
  constructor(private readonly told: ResizeObserverCallback) {}
  observe(target: Element) {
    this.targets.add(target);
    queueMicrotask(() => {
      if (this.targets.has(target))
        this.told(
          [{ target } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        );
    });
  }
  unobserve(target: Element) {
    this.targets.delete(target);
  }
  disconnect() {
    this.targets.clear();
  }
}

const list = () =>
  host.querySelector<HTMLUListElement>('ul[aria-label="Leads"]')!;
const drawn = () => [
  ...list().querySelectorAll<HTMLLIElement>("li[data-row-kind]"),
];
const topOf = (item: HTMLElement) =>
  Number(/translateY\(([-\d.]+)px\)/.exec(item.style.transform)?.[1]);
const allLeads = (
  <ListView
    canManage={false}
    stage="open"
    stageLabel="All leads"
    scope="mine"
    query=""
    version={0}
    onOpen={() => {}}
  />
);
async function settle() {
  for (let n = 0; n < 6; n += 1)
    await act(async () => {
      await Promise.resolve();
    });
}

// Native-feel plan, item 4 (3 Nov 2026): a row's height is read from a drawn
// row, never fixed, so the list holds at 200% text and in Devanagari.
it("reads its row height from a drawn row: at font scale 2.0 its rows stand 144 px apart", async () => {
  // The app sets the root font size from the phone's scale (window.SXFontScale)
  // and the type is in rem: at 2.0 a row measures 144 px.
  document.documentElement.style.fontSize = "200%";
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.matches("li[data-row-kind]") ? 144 : 0;
    },
  );
  vi.stubGlobal("ResizeObserver", Watch);
  await act(async () => root.render(allLeads));
  await settle();
  // As tall as all 30 rows at the measured height, each at its top.
  expect(list().style.height).toBe(`${30 * 144}px`);
  const rows = drawn();
  expect(rows[0].style.transform).toBe("translateY(0px)");
  expect(rows[1].style.transform).toBe("translateY(144px)");
  expect(rows[1].getAttribute("aria-posinset")).toBe("2");
  expect(rows[1].getAttribute("aria-setsize")).toBe("30");
  // A 900 px first view holds six such rows, plus six more: 13 of the 30.
  expect(rows.length).toBeLessThanOrEqual(13);
});

// Robot row 68ba6be1 (4 Nov 2026): on dev every row kept the 72 px guess and
// rows 79 to 99 px tall overlapped. React's strict mode mounts the list twice
// (a kept-alive tab shown again does the same): the watch must start again.
it("reads its rows' heights after a second mount, as React's strict mode does", async () => {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.matches("li[data-row-kind]") ? 88 : 0;
    },
  );
  vi.stubGlobal("ResizeObserver", Watch);
  await act(async () => root.render(<StrictMode>{allLeads}</StrictMode>));
  await settle();
  expect(list().style.height).toBe(`${30 * 88}px`);
  expect(drawn()[1].style.transform).toBe("translateY(88px)");
});

// The same robot row: a line wraps on some rows, so rows of one kind are not
// one height. Each row is placed below the last by its own height.
it("places each row below the last by that row's own height, so none overlap", async () => {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(
    function (this: HTMLElement) {
      if (!this.matches("li[data-row-kind]")) return 0;
      return Number(this.getAttribute("aria-posinset")) % 3 === 0 ? 99 : 79;
    },
  );
  vi.stubGlobal("ResizeObserver", Watch);
  await act(async () => root.render(allLeads));
  await settle();
  const rows = drawn();
  expect(rows.length).toBeGreaterThan(3);
  for (let at = 1; at < rows.length; at += 1)
    expect(topOf(rows[at]) - topOf(rows[at - 1])).toBe(
      rows[at - 1].offsetHeight,
    );
  // Rows 3, 6 and 9 read 99 px, the rest 79.
  expect(topOf(rows[3])).toBe(79 + 79 + 99);
});
