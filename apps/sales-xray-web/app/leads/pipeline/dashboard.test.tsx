// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../../notice-center", () => ({ notify: () => undefined }));
vi.mock("../../telemetry", () => ({
  track: () => undefined,
  waitBand: () => "unknown",
}));

import { fixtureReport } from "../../review-fixture/lead-pipeline/lead-pipeline-data";
import {
  PipelineDashboard,
  campaignTitle,
  minutesText,
  nowTitle,
  percent,
  talkText,
  wonPer100,
} from "./dashboard";
import type { CampaignRow, PipelineReport } from "./pipeline-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const serve = (report: PipelineReport) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(report), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("leads with outcomes, then campaigns and salespeople; the rest under See more", async () => {
  serve(fixtureReport());
  await act(async () => {
    root.render(<PipelineDashboard pipeline="main" />);
  });
  const text = container.textContent ?? "";
  const kpis = container.querySelector('[aria-label="Outcomes"]')?.textContent;
  expect(kpis).toContain("Reached");
  expect(kpis).toContain("72%");
  expect(kpis).toContain("14 min");
  expect(kpis).not.toContain("Late");
  // Campaigns: live first, a paused one after; won per 100 new leads.
  const campaigns = container.querySelector('[aria-label="Campaigns"]');
  expect(campaigns?.textContent).toContain("Live · 12 leads");
  expect(campaigns?.textContent).toContain("Paused · 6 leads");
  expect(campaigns?.textContent).toContain(
    "12 leads · 80% reached · 40% interested",
  );
  // Salespeople: wins first; a switch compares calls.
  const people = container.querySelector('[aria-label="Salespeople"]');
  expect(people?.textContent).toContain("Kavya Fictional wins most");
  const calls = [...(people?.querySelectorAll("button") ?? [])].find(
    (button) => button.textContent === "Calls",
  );
  await act(async () => calls?.click());
  expect(people?.textContent).toContain("Arjun Sample makes the most calls");
  // See more keeps where leads stand, how they move on, why they were lost, cities.
  const more = container.querySelector("details:last-of-type");
  expect(more?.querySelector("summary")?.textContent).toBe("See more");
  expect(text).toContain("2 late follow-ups");
  expect(text).toContain("13 of 18 leads");
  expect(text).toContain("Lost most often: price or budget");
  expect(text).toContain("Junk leads are left out of these.");
  expect(text).toContain("Most leads come from Pune: 9");
  expect(text).toContain("1 lead has a city we couldn’t place.");
  // Counts only: never money.
  expect(text).not.toMatch(/₹|\$|rupee/i);
});

it("All time says it counts old leads and folds ended campaigns", async () => {
  const report = fixtureReport();
  const old: CampaignRow = {
    ...(report.campaigns ?? [])[0],
    key: "csv:fictional old crm",
    label: "Fictional Old CRM",
    source: "csv",
    status: "ended",
    history: true,
    created: 40,
    won: 1,
    first_response_minutes: null,
  };
  serve({
    ...report,
    days: 0,
    history_leads: 40,
    campaigns: [...(report.campaigns ?? []), old],
  });
  await act(async () => {
    root.render(<PipelineDashboard pipeline="main" />);
  });
  const all = [...container.querySelectorAll("button")].find(
    (button) => button.textContent === "All time",
  );
  await act(async () => all?.click());
  expect(container.textContent).toContain(
    "Includes 40 old leads brought in as history.",
  );
  const fold = container.querySelector('[aria-label="Campaigns"] details');
  expect(fold?.querySelector("summary")?.textContent).toContain(
    "Ended · 40 leads",
  );
  expect(fold?.textContent).toContain("first call –");
});

it("says the numbers will come when there are few leads", async () => {
  serve({ ...fixtureReport(), enough: false, total: 4 });
  await act(async () => {
    root.render(<PipelineDashboard pipeline="main" />);
  });
  expect(container.textContent).toContain("Not enough leads yet: 4");
});

it("a seller sees their own numbers, without the team's rows", async () => {
  serve({ ...fixtureReport(), mine: true });
  await act(async () => {
    root.render(<PipelineDashboard pipeline="main" />);
  });
  expect(container.textContent).toContain("Your own leads.");
  expect(container.querySelector('[aria-label="Salespeople"]')).toBeNull();
});

it("words its numbers", () => {
  expect(percent(0.556)).toBe("56%");
  expect(percent(null)).toBe("–");
  expect(nowTitle({ total: 12, groups: { active: 7 } })).toBe(
    "12 leads, 7 still being worked",
  );
  expect(minutesText(34)).toBe("34 min");
  expect(minutesText(125)).toBe("2 h 5 min");
  expect(minutesText(null)).toBe("–");
  expect(talkText(15_300)).toBe("4 h 15 min");
  expect(wonPer100({ won: 2, created: 12 })).toBe(16.7);
  expect(wonPer100({ won: 0, created: 0 })).toBeNull();
});

it("says which campaigns win, never from too few leads", () => {
  const row = (status: CampaignRow["status"], created: number, won: number) =>
    ({
      ...(fixtureReport().campaigns ?? [])[0],
      status,
      created,
      won,
    }) as CampaignRow;
  expect(campaignTitle([row("live", 400, 10), row("ended", 2600, 13)])).toBe(
    "Live campaigns win 5 times as often as ended ones",
  );
  expect(campaignTitle([row("live", 400, 10), row("ended", 400, 9)])).toBe(
    "Live and ended campaigns win about as often",
  );
  expect(campaignTitle([{ ...row("live", 12, 2), label: "Rooftop" }])).toBe(
    "Rooftop wins most: 16.7 per 100 leads",
  );
  expect(campaignTitle([row("live", 3, 1)])).toBe(
    "Won per 100 leads, by campaign",
  );
});
