import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  backfillLine,
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
    "Bringing in older leads… 1 lead so far",
  );
  expect(backfillLine({ state: "done", created: 12, seen: 15 })).toBe(
    "Older leads: 12 leads from the last 90 days",
  );
  expect(backfillLine({ state: "done", created: 0, seen: 15 })).toBe(
    "Older leads: none missing from the last 90 days",
  );
});

it("shows a Page's forms and brings in older leads on request", async () => {
  await render();
  expect(tile().textContent).toContain(
    "All forms, new ones too: Enquiry, Site visit (archived)",
  );
  expect(tile().textContent).toContain(
    "Older leads: 12 leads from the last 90 days",
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
    "30 older leads came in; the rest follow in the next few minutes.",
  );
  expect(tile().textContent).toContain(
    "Bringing in older leads… 30 leads so far",
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
  const help = tile().querySelector("details") as HTMLDetailsElement;
  expect(help.open).toBe(true);
  expect(help.textContent).toContain("Assign CRMs and choose Sales Xray Leads");
  expect(help.querySelector("a")?.getAttribute("href")).toBe(
    "https://business.facebook.com/settings/leads-accesses",
  );
});

it("keeps the Leads Access Manager steps folded away when nothing is wrong", async () => {
  await render();
  const help = tile().querySelector("details") as HTMLDetailsElement;
  expect(help.open).toBe(false);
  expect(help.querySelector("summary")?.textContent).toBe(
    "Does your business use Leads Access Manager?",
  );
});
