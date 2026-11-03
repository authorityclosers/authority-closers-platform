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
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly told: ResizeObserverCallback) {}
      observe() {
        queueMicrotask(() => this.told([], this as unknown as ResizeObserver));
      }
      unobserve() {}
      disconnect() {}
    },
  );
  await act(async () =>
    root.render(
      <ListView
        canManage={false}
        stage="open"
        stageLabel="All leads"
        scope="mine"
        query=""
        version={0}
        onOpen={() => {}}
      />,
    ),
  );
  await act(async () => {
    await Promise.resolve();
  });
  const list = host.querySelector<HTMLUListElement>('ul[aria-label="Leads"]')!;
  // As tall as all 30 rows at the measured height, each at its top.
  expect(list.style.height).toBe(`${30 * 144}px`);
  const drawn = [...list.querySelectorAll<HTMLLIElement>("li[data-row-kind]")];
  expect(drawn[0].style.transform).toBe("translateY(0px)");
  expect(drawn[1].style.transform).toBe("translateY(144px)");
  expect(drawn[1].getAttribute("aria-posinset")).toBe("2");
  expect(drawn[1].getAttribute("aria-setsize")).toBe("30");
  // A 900 px first view holds six such rows, plus six more: 13 of the 30.
  expect(drawn.length).toBeLessThanOrEqual(13);
});
