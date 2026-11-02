import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  backfillChip,
  backfillLine,
  checkedLine,
  formsLine,
  SourcesView,
  type MetaPage,
} from "./sources-view";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=sources"),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const page = (extra: Partial<MetaPage> = {}): MetaPage => ({
  pageId: "1326368220570095",
  name: "Fictional Homes",
  active: true,
  received: 4,
  lastPulledAt: null,
  forms: "all",
  formsCovered: [
    { id: "f1", name: "Enquiry", status: "ACTIVE" },
    { id: "f2", name: "Site visit", status: "ARCHIVED" },
  ],
  backfill: { state: "done", created: 12, seen: 15 },
  problem: null,
  ...extra,
});

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string }[];
let pages: MetaPage[];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  calls = [];
  pages = [page()];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (url.endsWith("/meta/status"))
        return json({ configured: true, pages });
      if (url.endsWith("/backfill") && method === "POST") {
        pages = [
          page({ backfill: { state: "running", created: 30, seen: 30 } }),
        ];
        return json({ page: pages[0], imported: 30 });
      }
      if (url.endsWith("/google/status"))
        return json({ configured: false, accounts: [] });
      return json({ sources: [] });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const render = async () => {
  await act(async () =>
    root.render(
      <SourcesView sandbox={false} onChanged={() => {}} onImport={() => {}} />,
    ),
  );
};

const tile = () => host.querySelector('[data-brand="meta"]') as HTMLElement;

it("says which forms bring leads in, new ones included", () => {
  expect(formsLine(page())).toBe(
    "All forms, new ones too: Enquiry, Site visit (archived)",
  );
  expect(formsLine(page({ formsCovered: [] }))).toBe(
    "All forms on this Page, new ones too",
  );
  expect(
    formsLine(
      page({
        forms: ["f1"],
        formsCovered: [{ id: "f1", name: "Enquiry", status: "ACTIVE" }],
      }),
    ),
  ).toBe("Forms: Enquiry");
});

it("says where bringing in older leads has got to", () => {
  expect(backfillLine(null)).toBeNull();
  expect(backfillLine({ state: "running", created: 1, seen: 3 })).toBe(
    "Bringing in older leads… 3 leads read: 1 new, 0 already in your leads so far",
  );
  expect(backfillLine({ state: "done", created: 12, seen: 15 })).toBe(
    "Older leads, last 90 days: 15 leads read: 12 new, 0 already in your leads",
  );
  // Bug report #10: every lead was already here, and it says so.
  expect(
    backfillLine({
      state: "done",
      created: 0,
      seen: 100,
      linked: 98,
      known: 2,
    }),
  ).toBe(
    "Older leads, last 90 days: 100 leads read: 0 new, 100 already in your leads",
  );
  expect(backfillLine({ state: "done", created: 0, seen: 0 })).toBe(
    "Older leads: Meta has none from the last 90 days",
  );
});

// Owner, 2 Nov 2026: Pages, forms and older leads are managed in one place,
// Leads setup → Sources; this tile says what is connected and working.
it("says what is connected and sends Page changes to Leads setup", async () => {
  await render();
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  expect(tile().textContent).toContain(
    "1 Facebook account · 1 Page bringing leads",
  );
  const manage = [...tile().querySelectorAll("a")].find(
    (link) => link.textContent === "Manage Pages",
  );
  expect(manage?.getAttribute("href")).toBe(
    "/organisation?tab=leads&part=sources",
  );
  // No Page or form rows, switches or older-leads buttons here any more.
  expect(tile().querySelector('[role="switch"]')).toBeNull();
  expect(tile().textContent).not.toContain("Bring old leads");
  expect(calls.every((call) => call.method === "GET")).toBe(true);
});

it("walks the customer through Leads Access Manager when Meta blocks the app", async () => {
  pages = [
    page({
      backfill: { state: "blocked", created: 0, seen: 0 },
      problem: {
        kind: "lead_access",
        text: "Your business limits which apps can read this Page's leads (Meta's Leads Access Manager). Allow Sales Xray there, then press Check now.",
      },
    }),
  ];
  await render();
  // The Page's own words are on its card in Leads setup → Sources; here the
  // steps open by themselves.
  const help = [...tile().querySelectorAll("details")].find((item) =>
    item.textContent?.includes("Leads Access Manager"),
  ) as HTMLDetailsElement;
  expect(help.open).toBe(true);
  expect(help.textContent).toContain("Assign CRMs and choose Sales Xray Leads");
  expect(help.querySelector("a")?.getAttribute("href")).toBe(
    "https://business.facebook.com/settings/leads-accesses",
  );
});

it("keeps the Leads Access Manager steps folded away when nothing is wrong", async () => {
  await render();
  const help = [...tile().querySelectorAll("details")].find((item) =>
    item.textContent?.includes("Leads Access Manager"),
  ) as HTMLDetailsElement;
  expect(help.open).toBe(false);
  expect(help.querySelector("summary")?.textContent).toBe(
    "Does your business use Leads Access Manager?",
  );
});

it("says the Pages didn't load, with Try again, instead of loading forever", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push({ url, method: "GET" });
      if (url.endsWith("/meta/status")) throw new TypeError("network down");
      if (url.endsWith("/google/status"))
        return json({ configured: false, accounts: [] });
      return json({ sources: [] });
    }),
  );
  await render();
  expect(tile().textContent).toContain("Didn't load");
  const again = [...tile().querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Try again"),
  ) as HTMLButtonElement;
  const before = calls.filter((call) =>
    call.url.endsWith("/meta/status"),
  ).length;
  await act(async () => again.click());
  expect(calls.filter((call) => call.url.endsWith("/meta/status")).length).toBe(
    before + 1,
  );
});

it("keeps new leads apart from people who asked again after Check now", () => {
  expect(checkedLine("Fictional Homes", 0, 0)).toBe(
    "No new leads from Fictional Homes.",
  );
  expect(checkedLine("Fictional Homes", 2, 0)).toBe(
    "2 new leads from Fictional Homes.",
  );
  expect(checkedLine("Fictional Homes", 1, 3)).toBe(
    "1 new lead, 3 people asked again from Fictional Homes.",
  );
});

it("says a run of older leads in a chip's few words", () => {
  expect(backfillChip(null)).toBeNull();
  expect(backfillChip({ state: "running", created: 2, seen: 40 })).toBe(
    "Old leads: 40 read",
  );
  expect(
    backfillChip({ state: "done", created: 0, seen: 104, known: 104 }),
  ).toBe("Old leads: 0 new, 104 already here");
  expect(backfillChip({ state: "done", created: 0, seen: 0 })).toBe(
    "No old leads on Meta",
  );
  expect(backfillChip({ state: "blocked", created: 0, seen: 0 })).toBe(
    "Old leads stopped",
  );
});
