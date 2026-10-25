import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
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

it("shows a Page's forms and brings in older leads on request", async () => {
  await render();
  expect(tile().textContent).toContain(
    "All forms, new ones too: Enquiry, Site visit (archived)",
  );
  expect(tile().textContent).toContain(
    "Older leads, last 90 days: 15 leads read: 12 new, 0 already in your leads",
  );
  const older = [...tile().querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Bring in older leads"),
  ) as HTMLButtonElement;
  await act(async () => older.click());
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/meta/pages/1326368220570095/backfill",
    method: "POST",
  });
  expect(tile().textContent).toContain(
    "30 older leads read: 30 new, 0 already in your leads; the rest follow in the next few minutes.",
  );
  expect(tile().textContent).toContain(
    "Bringing in older leads… 30 leads read: 30 new, 0 already in your leads so far",
  );
  // While it runs, there is nothing to press again.
  expect(
    [...tile().querySelectorAll("button")].some((button) =>
      button.textContent?.includes("Bring in older leads"),
    ),
  ).toBe(false);
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
  expect(tile().textContent).toContain("Allow Sales Xray there");
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

it("lists every form on the Page to pick from, and brings in the picked ones' older leads", async () => {
  pages = [
    page({
      account: { name: "Fictional Owner", picture: null },
      formsOnPage: [
        { id: "f1", name: "Enquiry", status: "ACTIVE", leads: 31 },
        { id: "f2", name: "Site visit", status: "ARCHIVED", leads: 4 },
        { id: "f3", name: "Old offer", status: "ACTIVE", leads: 0 },
      ],
    }),
  ];
  const bodies: unknown[] = [];
  const base = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body) bodies.push(JSON.parse(String(init.body)));
      return base(input, init);
    }),
  );
  await render();
  // Bug report #8: which Facebook account the Page came through.
  expect(tile().textContent).toContain("Through Fictional Owner's Facebook");
  expect(tile().textContent).toContain("Forms on this Page (3)");
  expect(tile().textContent).toContain("31 on Meta");
  expect(tile().textContent).toContain("Archived");
  const boxes = [
    ...tile().querySelectorAll('input[type="checkbox"]'),
  ] as HTMLInputElement[];
  // Select all starts on; untick it, then pick one form.
  expect(boxes[0].checked).toBe(true);
  await act(async () => boxes[0].click());
  await act(async () => boxes[2].click());
  const bring = [...tile().querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Bring old leads (1)"),
  ) as HTMLButtonElement;
  await act(async () => bring.click());
  expect(calls).toContainEqual({
    url: "/v1/lead-desk/meta/pages/1326368220570095/backfill",
    method: "POST",
  });
  expect(bodies).toContainEqual({ forms: ["f2"] });
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
