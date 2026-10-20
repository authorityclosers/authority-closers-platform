// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import {
  costQuery,
  normalizeMetrics,
  personWords,
  rateWords,
  scopeView,
} from "./cost-data";
import { ScopeFilters, type CostFilter } from "./cost-views";

const ASHA = "p_0123456789abcdef";
const RAVI = "p_fedcba9876543210";

const metrics = normalizeMetrics({
  window: { days: 30 },
  here: "development",
  fx: {
    currency: "USD",
    mode: "daily",
    usd_to_inr: 88.12,
    set_on: "2026-10-20",
    planning_usd_to_inr: 100,
    latest: { day: "2026-10-20", usd_to_inr: 88.3 },
    unrated_steps: 0,
    problem: null,
  },
  filters: { company: null, stage: null, person: ASHA },
  choices: {
    companies: [],
    people: [
      {
        id: ASHA,
        environment: "development",
        name: "Asha (fictional)",
        rupees: 88.12,
      },
      { id: RAVI, environment: "staging", name: null, rupees: 44.06 },
    ],
    people_available: ["development", "staging"],
    stages: [],
  },
});

const current: CostFilter = {
  tab: "overview",
  days: "30",
  env: "all",
  tests: false,
  person: ASHA,
};

it("reads people and the daily rate, and words both", () => {
  expect(metrics.filters.person).toBe(ASHA);
  expect(metrics.choices.people.map(personWords)).toEqual([
    "Asha (fictional)",
    "Person fedcba",
  ]);
  expect(metrics.fx).toMatchObject({
    mode: "daily",
    usdToInr: 88.12,
    latest: { day: "2026-10-20", usdToInr: 88.3 },
  });
  expect(rateWords(metrics.fx)).toMatch(
    /^each day's ECB rate \(latest ₹88\.3 per \$1, 20 Oct 2026\)$/,
  );
  const planning = normalizeMetrics({
    fx: { usd_to_inr: 100, set_on: "2026-09-19" },
  });
  expect(planning.fx.mode).toBe("planning");
  expect(rateWords(planning.fx)).toMatch(/^₹100 per \$1, set 19 Sept? 2026$/);
});

it("keeps one person and the planning rate in the link, and nothing malformed", () => {
  expect(scopeView({ person: ASHA, fx: "planning" })).toEqual({
    person: ASHA,
    fx: "planning",
  });
  expect(scopeView({ person: "p_NOPE", fx: "weekly" })).toEqual({});
  expect(costQuery(current, {})).toBe(`/usage?person=${ASHA}`);
  expect(costQuery(current, { fx: "planning", person: undefined })).toBe(
    "/usage?fx=planning",
  );
});

it("offers people by name here and by pseudonym elsewhere, with the rate switch", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <ScopeFilters metrics={metrics} current={current} />,
  );
  const options = [
    ...host.querySelectorAll<HTMLOptionElement>('select[name="person"] option'),
  ].map((item) => item.textContent ?? "");
  expect(options[0]).toBe("Everyone");
  expect(options[1]).toContain("Asha (fictional)");
  expect(options[2]).toContain("Person fedcba");
  const text = host.textContent ?? "";
  expect(text).toContain("Showing Asha (fictional)");
  expect(text).toContain("Rupees at each day's ECB rate");
  const toggle = [...host.querySelectorAll("a")].find((a) =>
    a.textContent?.startsWith("Use the planning rate"),
  );
  expect(toggle?.getAttribute("href")).toBe(
    `/usage?person=${ASHA}&fx=planning`,
  );
  expect(text).toContain("Names show for this Admin's own environment");
});
