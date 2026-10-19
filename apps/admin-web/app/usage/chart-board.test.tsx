/** The Overview's chart picker and comparison (owner, 19 Oct 2026). */
import type { AnchorHTMLAttributes } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { normalizeMetrics } from "./cost-data";
import { ChartBoard } from "./cost-views";

vi.mock("next/link", () => ({
  default: (
    props: AnchorHTMLAttributes<HTMLAnchorElement> & { scroll?: boolean },
  ) => {
    const anchor = { ...props };
    delete anchor.scroll;
    return <a {...anchor} />;
  },
}));

const metrics = normalizeMetrics({
  overview: {
    spend_window: 10,
    audio_minutes: 12,
    daily: [
      {
        day: "2026-10-17",
        by_environment: { staging: 2 },
        spend: 2,
        audio_minutes: 4,
        per_minute: 0.5,
        calls: 1,
      },
      {
        day: "2026-10-18",
        by_environment: { staging: 4, development: 1 },
        spend: 5,
        audio_minutes: 8,
        per_minute: 0.625,
        calls: 2,
      },
      {
        day: "2026-10-19",
        by_environment: { development: 3 },
        spend: 3,
        audio_minutes: 0,
        per_minute: null,
        calls: 0,
      },
    ],
  },
});
const base = { tab: "overview", days: "30", env: "all", tests: false };

it("shows the two usual charts, a picker for the rest and a hide button on each", () => {
  const html = renderToStaticMarkup(
    <ChartBoard metrics={metrics} current={base} windowLabel="30 days" />,
  );
  expect(html).toContain("Spend per day");
  expect(html).toContain("Cost per audio minute");
  expect(html).toContain('aria-label="Hide Spend per day"');
  expect(html).toContain('href="/usage?charts=perMinute"');
  // The picker offers the other series, linked to add them.
  expect(html).toContain('href="/usage?charts=spend%2CperMinute%2Ccalls"');
  expect(html).not.toContain("Stop comparing");
});

it("draws two chosen series on one chart, with a day-by-day table", () => {
  const html = renderToStaticMarkup(
    <ChartBoard
      metrics={metrics}
      current={{ ...base, charts: "calls", ca: "spend", cb: "calls" }}
      windowLabel="30 days"
    />,
  );
  expect(html).toContain("Spend per day and Calls analysed");
  expect(html.match(/<polyline/g)?.length).toBe(2);
  expect(html).toContain("Day by day");
  expect(html).toContain('href="/usage?charts=calls"');
  // Only the chosen chart shows below the comparison.
  expect(html).toContain('aria-label="Hide Calls analysed"');
  expect(html).not.toContain('aria-label="Hide Spend per day"');
});

it("says so when every chart is hidden", () => {
  const html = renderToStaticMarkup(
    <ChartBoard
      metrics={metrics}
      current={{ ...base, charts: "none" }}
      windowLabel="30 days"
    />,
  );
  expect(html).toContain("All charts are hidden. Pick any above.");
});
