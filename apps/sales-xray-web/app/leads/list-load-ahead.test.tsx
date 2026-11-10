// @vitest-environment happy-dom
import { act } from "react";
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

// The browser's watch on the list's end, by hand: each keeps how it was asked
// to watch, and the test says when the end comes near and where its top is
// (the screen's bottom is 900, below the content area's top).
type Told = (
  entries: { isIntersecting: boolean; boundingClientRect: { top: number } }[],
) => void;
type Watching = {
  told: Told;
  options: IntersectionObserverInit | undefined;
  on: boolean;
  observed: number;
};
let watches: Watching[];
class Near {
  private readonly own: Watching;
  constructor(told: Told, options?: IntersectionObserverInit) {
    this.own = { told, options, on: false, observed: 0 };
    watches.push(this.own);
  }
  observe() {
    this.own.on = true;
    this.own.observed += 1;
  }
  unobserve() {}
  disconnect() {
    this.own.on = false;
  }
}
const live = () => watches.filter((watch) => watch.on);
const near = (top = 3000) =>
  act(async () => {
    for (const watch of live())
      watch.told([{ isIntersecting: true, boundingClientRect: { top } }]);
  });
async function settle() {
  for (let n = 0; n < 6; n += 1)
    await act(async () => {
      await Promise.resolve();
    });
}

// 160 leads, 50 a page.
let scroller: HTMLDivElement;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  localStorage.clear();
  vi.mocked(readLeads).mockClear();
  watches = [];
  vi.stubGlobal("IntersectionObserver", Near);
  vi.mocked(readLeads).mockImplementation(async ({ offset = 0 }) => {
    const to = Math.min(offset + 50, 160);
    return {
      leads: Array.from({ length: to - offset }, (_, n) => row(offset + n)),
      total: 160,
      next_offset: to < 160 ? to : null,
    };
  });
  // On a computer the list scrolls in the app's content area, not the page.
  scroller = document.createElement("div");
  scroller.style.overflowY = "auto";
  scroller.getBoundingClientRect = () =>
    ({ top: 0, bottom: 900, left: 0, right: 1440 }) as DOMRect;
  host = document.createElement("div");
  scroller.append(host);
  document.body.append(scroller);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  scroller.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

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
const asked = () =>
  vi.mocked(readLeads).mock.calls.map(([ask]) => ask.offset ?? 0);

// QA robot 64de155b (9 Nov 2026): at 1440 the list's end (Show more, the
// quick add) jumped off screen when the next page came, 0.09 each page. The
// watch was page-wide, and the content area hid the end from it until the end
// was on screen.
it("watches the end in the list's own scroller, 2400 px ahead, and again after each page", async () => {
  await act(async () => root.render(allLeads));
  await settle();
  expect(asked()).toEqual([0]);
  const first = live();
  expect(first).toHaveLength(1);
  expect(first[0].options?.root).toBe(scroller);
  expect(first[0].options?.rootMargin).toBe("2400px 0px");

  await near();
  await settle();
  expect(asked()).toEqual([0, 50]);
  // A fresh watch after the page, which a browser tells at once: if the end
  // is still near, the next page comes too.
  expect(live()).toHaveLength(1);
  expect(live()[0]).not.toBe(first[0]);
  await near();
  await settle();
  expect(asked()).toEqual([0, 50, 100]);
});

// The robot's part 2: someone at the end by keyboard had the next page push
// the end off screen. The list has no quick add since 10 Nov 2026 (the owner,
// his OnePlus: it didn't work and didn't belong); Show more is the end.
it("holds the next page while someone is at the end by keyboard, and goes on after", async () => {
  await act(async () => root.render(allLeads));
  await settle();
  const more = [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.startsWith("Show more"),
  );
  expect(more).toBeDefined();
  expect(host.querySelector('input[aria-label="New lead\'s name"]')).toBeNull();

  await act(async () => more!.focus());
  await near();
  await settle();
  expect(asked()).toEqual([0]);

  await act(async () => more!.blur());
  await near();
  await settle();
  expect(asked()).toEqual([0, 50]);
});

// The robot's recheck, 9 Nov 2026: scrolled straight to the quick add, the end
// was on screen when the list first saw it, and the next page pushed it off
// (0.094). Show more is right there; once the page moves, the list looks again.
it("leaves an end already on screen where it is, and looks again once the page moves", async () => {
  await act(async () => root.render(allLeads));
  await settle();
  const watch = live()[0];
  const looks = watch.observed;

  await near(700);
  await settle();
  expect(asked()).toEqual([0]);

  await act(async () => scroller.dispatchEvent(new Event("scroll")));
  expect(watch.observed).toBe(looks + 1);
  await near(1400);
  await settle();
  expect(asked()).toEqual([0, 50]);
});
