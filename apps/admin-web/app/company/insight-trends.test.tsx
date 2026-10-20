// @vitest-environment happy-dom
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { normalizeAnalysis } from "./analysis-data";
import {
  FunnelPanel,
  PeoplePanel,
  SKILL_WEEKS,
  SkillWeeksPanel,
  WeeklyPanel,
  band,
  weekLabel,
} from "./insight-trends";

const WEEKS = ["2026-10-05", "2026-10-12", "2026-10-19"];

const DATA = normalizeAnalysis({
  window: { days: 21 },
  calls: 9,
  calls_analysed: 7,
  calls_scored: 5,
  weeks: [
    { week: WEEKS[0], calls: 2, analysed: 2, scored: 1, average: 44 },
    { week: WEEKS[1], calls: 4, analysed: 3, scored: 3, average: 63 },
    { week: WEEKS[2], calls: 3, analysed: 2, scored: 1, average: 81 },
  ],
  skill_weeks: [
    {
      label: "Discovery",
      weeks: [
        { week: WEEKS[0], average: 40, calls: 1 },
        { week: WEEKS[1], average: null, calls: 0 },
        { week: WEEKS[2], average: 75, calls: 1 },
      ],
    },
  ],
  people: [
    {
      person_id: "p-1",
      name: "Asha (fictional)",
      calls: 6,
      analysed: 5,
      scored: 4,
      average: 58,
      needs_work_share: 0.375,
      weakest: { label: "Discovery", average: 41, calls: 4 },
      weeks: [1, 3, 2],
    },
    {
      person_id: "p-2",
      name: "Ravi (fictional)",
      calls: 3,
      analysed: 2,
      scored: 0,
      average: null,
      needs_work_share: null,
      weakest: null,
      weeks: [0, 1, 2],
    },
  ],
  stages: {
    version: 2,
    leads: 40,
    funnel: [
      {
        key: "new",
        label: "New enquiry",
        reached: 40,
        share: 1,
        from_previous: null,
      },
      {
        key: "visit",
        label: "Site visit",
        reached: 12,
        share: 0.3,
        from_previous: 0.3,
      },
      {
        key: "won",
        label: "Booked",
        reached: 3,
        share: 0.075,
        from_previous: 0.25,
      },
    ],
    lost: 9,
    unreachable: 6,
  },
});

const EMPTY = normalizeAnalysis({ window: { days: 30 } });

const html = (element: ReactElement) => renderToStaticMarkup(element);

it("trends calls and the mean score by week, each with its count", () => {
  const out = html(<WeeklyPanel data={DATA} />);
  expect(out).toContain("9 calls · 7 read by the engine · 5 scored");
  expect(out).toContain(
    "Week of 12 Oct: 4 calls, 3 read, 3 scored, mean score 63 from 3 calls",
  );
  expect(out).toContain('data-band="low"'); // 44
  expect(out).toContain('data-band="high"'); // 81
  expect(out).not.toContain("no scores");
  expect(html(<WeeklyPanel data={EMPTY} />)).toContain(
    "No calls were uploaded in this window",
  );
  const unscored = normalizeAnalysis({
    calls: 1,
    weeks: [
      { week: WEEKS[0], calls: 1, analysed: 0, scored: 0, average: null },
    ],
  });
  expect(html(<WeeklyPanel data={unscored} />)).toContain(
    "a call is scored after its report is ready",
  );
});

it("shows each skill's score over the weeks with the calls behind each", () => {
  const host = document.createElement("div");
  host.innerHTML = html(<SkillWeeksPanel data={DATA} />);
  const cells = [...host.querySelectorAll("tbody td")];
  expect(cells.map((cell) => cell.textContent)).toEqual(["401", "—", "751"]);
  expect(cells[0].getAttribute("title")).toBe("40 from 1 call");
  expect(cells[1].getAttribute("title")).toBe("No scored calls");
  expect(host.textContent).toContain("5 calls scored");
  expect(html(<SkillWeeksPanel data={EMPTY} />)).toContain(
    "skill trends start with the first scored call",
  );
  expect(SKILL_WEEKS).toBe(12);
});

it("shows how far leads got along the organisation's own stages", () => {
  const out = html(<FunnelPanel data={DATA} />);
  expect(out).toContain("40 leads created in this window");
  expect(out).toContain("the organisation&#x27;s own stages (version 2)");
  expect(out).toContain("Site visit");
  expect(out).toContain("30% of leads · 30% of the stage before");
  expect(out).toContain("8% of leads · 25% of the stage before");
  expect(out).toContain("6 couldn’t be reached · 9 lost");
  const none = html(<FunnelPanel data={EMPTY} />);
  expect(none).toContain("Lead Desk&#x27;s default stages");
  expect(none).toContain("No leads were created in Lead Desk in this window");
});

it("lists each salesperson's calls, scores and weakest skill with counts", () => {
  const host = document.createElement("div");
  host.innerHTML = html(<PeoplePanel data={DATA} />);
  const rows = [...host.querySelectorAll("tbody tr")];
  expect(rows).toHaveLength(2);
  expect(rows[0].textContent).toContain("Asha (fictional)");
  expect(rows[0].textContent).toContain("5 / 4");
  expect(rows[0].textContent).toContain("38%");
  expect(rows[0].textContent).toContain("Discovery · 41 (4 calls)");
  expect(rows[0].querySelector('[role="img"]')).not.toBeNull(); // 3 busy weeks
  expect(rows[1].textContent).toContain("—");
  expect(html(<PeoplePanel data={EMPTY} />)).toContain(
    "No salesperson uploaded a call in this window",
  );
});

it("labels weeks and bands scores", () => {
  expect(weekLabel("2026-10-19")).toBe("19 Oct");
  expect(weekLabel("not a week")).toBe("not a week");
  expect([band(null), band(49), band(50), band(70)]).toEqual([
    "none",
    "low",
    "mid",
    "high",
  ]);
});
