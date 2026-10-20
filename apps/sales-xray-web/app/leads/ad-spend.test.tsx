import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  AdSpendPanel,
  money,
  spendLine,
  SpendSummary,
  type SpendReport,
} from "./ad-spend";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const REPORT: SpendReport = {
  configured: true,
  connected: true,
  syncedAt: new Date().toISOString(),
  error: null,
  accounts: 1,
  start: "2026-09-20",
  end: "2026-10-19",
  totals: [
    { currency: "INR", spend: "1200.00", leads: 5, won: 1, perLead: "240.00" },
  ],
  campaigns: [
    {
      campaignId: "1",
      campaignName: "3 BHK enquiries",
      adAccountId: "act_101",
      currency: "INR",
      spend: "1100.00",
      impressions: 2000,
      clicks: 80,
      metaLeads: 6,
      leads: 4,
      won: 1,
      perLead: "275.00",
      perCustomer: "1100.00",
    },
  ],
};

let root: Root;
let host: HTMLDivElement;
let report: SpendReport;
let calls: { url: string; method: string }[];

beforeEach(() => {
  report = REPORT;
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? "GET" });
      const body =
        init?.method === "POST"
          ? {
              ...report,
              error: "Continue with Meta again to read your ad spend.",
            }
          : report;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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

it("writes money in the account's own currency, and one line per currency", () => {
  expect(money("1234.56", "INR")).toBe("₹1,235");
  expect(money(null, "INR")).toBe("–");
  expect(spendLine(REPORT)).toBe("₹1,200 spent in 30 days · ₹240 a lead");
  expect(
    spendLine({
      ...REPORT,
      totals: [
        { currency: "USD", spend: "9.00", leads: 0, won: 0, perLead: null },
      ],
    }),
  ).toBe("$9 spent in 30 days · no leads here yet");
  expect(spendLine({ ...REPORT, totals: [] })).toBeNull();
});

it("shows each campaign's spend, its leads here and what each cost", async () => {
  await act(async () => root.render(<AdSpendPanel />));
  expect(calls[0].url).toBe("/v1/lead-desk/meta/spend?days=30");
  const text = host.textContent ?? "";
  expect(text).toContain("Ads: what each lead cost");
  expect(text).toContain("3 BHK enquiries");
  expect(text).toContain("₹1,100");
  expect(text).toContain("(Meta counts 6)");
  expect(text).toContain("₹275");

  const check = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Check now"),
  ) as HTMLButtonElement;
  await act(async () => check.click());
  // The card's logo reads the brand library too; find the refresh itself.
  expect(
    calls.find((call) =>
      call.url.startsWith("/v1/lead-desk/meta/spend/refresh"),
    ),
  ).toEqual({
    url: "/v1/lead-desk/meta/spend/refresh?days=30",
    method: "POST",
  });
  expect(host.textContent).toContain("Continue with Meta again");
});

it("puts one line under the Facebook & Instagram source", async () => {
  await act(async () => root.render(<SpendSummary />));
  expect(host.textContent).toBe("₹1,200 spent in 30 days · ₹240 a lead");
});

it("stays hidden until the organisation has connected Meta", async () => {
  report = { ...REPORT, connected: false, campaigns: [], totals: [] };
  await act(async () => root.render(<AdSpendPanel />));
  expect(host.textContent).toBe("");
});

it("shows nothing, and no warning, when the Meta connection has no ads_read", async () => {
  report = {
    ...REPORT,
    needsAdsRead: true,
    error: null,
    campaigns: [],
    totals: [],
  };
  await act(async () =>
    root.render(
      <>
        <AdSpendPanel />
        <SpendSummary />
      </>,
    ),
  );
  expect(host.textContent).toBe("");
});
