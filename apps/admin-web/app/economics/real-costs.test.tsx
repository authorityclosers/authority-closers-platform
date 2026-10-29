// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => undefined }),
}));

import { economicsFixture } from "../review-fixture/economics/economics-fixture";
import { realCostsFixture } from "../review-fixture/economics/real-costs-fixture";
import { toItem, type RegisterRow } from "./cost-register-editor";
import {
  cadenceLine,
  normalizeCosts,
  normalizeEconomics,
} from "./economics-data";
import { EconomicsView } from "./economics-view";

const withRegister = () => ({ ...economicsFixture(), ...realCostsFixture() });

const mount = (raw: unknown) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <EconomicsView economics={normalizeEconomics(raw)} />,
  );
  return host;
};

it("reads the register's month, products and keys", () => {
  const economics = normalizeEconomics(withRegister());
  const costs = economics.costs;
  expect(costs?.total).toBe(31_420);
  expect(costs?.byCategory[0]).toMatchObject({
    key: "ai_subscriptions",
    rupees: 20_000,
  });
  expect(costs?.products.map((row) => row.key)).toEqual([
    "sales_xray",
    "learner",
    "other_companies",
    "company",
  ]);
  expect(costs?.overall.breakEvenPersonal).toBe(19);
  expect(costs?.keys.cpu).toEqual({ apps: 0.7, agents: 0.27, other: 0.03 });
  expect(economics.moneyIn).toEqual({ netMonth: 4118.04, payingAccounts: 2 });
  const phone = costs?.items.find((row) => row.key === "test_phone");
  expect(phone && cadenceLine(phone)).toBe("One-time ₹17,472 over 24 months");
  const router = costs?.items.find((row) => row.key === "router_credits");
  expect(router && cadenceLine(router)).toBe("Usage (a month) USD 40 (₹3,500)");
  // Before the first cost is entered the API sends no picture.
  expect(normalizeEconomics(economicsFixture()).costs).toBeNull();
  expect(normalizeCosts(null)).toBeNull();
});

it("shows the real month, profit or loss by product and every cost", () => {
  const text = mount(withRegister()).textContent ?? "";
  expect(text).toContain("Real cost a month");
  expect(text).toContain("₹31,420");
  expect(text).toContain("AC profit a month");
  expect(text).toContain("−₹27,302");
  expect(text).toContain("By category");
  expect(text).toContain("By cost centre");
  expect(text).toContain("Profit and loss by product");
  expect(text).toContain("AC overall");
  expect(text).toContain("17.4 Personal or 3 seats");
  expect(text).toContain("Every cost");
  expect(text).toContain(
    "Anthropic · Claude plan for the agents (illustrative)",
  );
  expect(text).toContain("23 months left to spread");
  expect(text).toContain("Not counted this month");
  expect(text).toContain("Agent work measured 2026-10-30 over 30 days.");
  expect(text).toContain("Server time: apps 70%, agents 27%, other 3%.");
  expect(text).toContain("Edit the cost register");
  // The old fixed list gives way to the register.
  expect(text).not.toContain("Edit fixed costs");
});

it("keeps the fixed list until the register starts, and offers to start it", () => {
  const host = mount(economicsFixture());
  const text = host.textContent ?? "";
  expect(text).toContain("Fixed costs a month");
  expect(text).toContain("Start the cost register");
  expect(text).not.toContain("Real cost a month");
  const buttons = Array.from(host.querySelectorAll("button[type=submit]")).map(
    (button) => button.textContent,
  );
  expect(buttons).toEqual(["Save fixed costs", "Save the cost register"]);
});

const row = (patch: Partial<RegisterRow>): RegisterRow => ({
  key: "phone",
  vendor: "Phone shop",
  label: "Test phone",
  category: "devices",
  centre: "sales_xray",
  cadence: "one_time",
  rupees: "17472",
  currency: "INR",
  original: "",
  started: "2026-10-02",
  ended: "",
  life: "24",
  rule: "direct",
  product: "sales_xray",
  tool: "all",
  shares: {},
  source: "invoice",
  evidence: " Order 1 ",
  ...patch,
});

it("turns an edited row into the API's item or says what is missing", () => {
  expect(toItem(row({}))).toEqual({
    key: "phone",
    vendor: "Phone shop",
    label: "Test phone",
    category: "devices",
    centre: "sales_xray",
    cadence: "one_time",
    rupees: 17472,
    currency: "INR",
    allocation: { rule: "direct", product: "sales_xray" },
    source: "invoice",
    started: "2026-10-02",
    life_months: 24,
    evidence: "Order 1",
  });
  expect(
    toItem(
      row({
        cadence: "usage",
        currency: "usd",
        original: "40",
        rule: "token_burn",
        tool: "claude",
      }),
    ),
  ).toMatchObject({
    currency: "USD",
    original: 40,
    allocation: { rule: "token_burn", tool: "claude" },
  });
  expect(toItem(row({ started: "" }))).toBe(
    "Test phone: a one-time cost needs the day it was bought.",
  );
  expect(toItem(row({ vendor: "" }))).toBe(
    "Test phone: give a vendor and an item.",
  );
  expect(toItem(row({ rupees: "-1" }))).toBe(
    "Test phone: the rupee amount is 0 or more.",
  );
  expect(
    toItem(row({ rule: "fixed", shares: { sales_xray: "60", company: "30" } })),
  ).toBe("Test phone: the shares add up to 100%.");
  expect(
    toItem(
      row({
        rule: "fixed",
        shares: { sales_xray: "75", company: "25", learner: "" },
      }),
    ),
  ).toMatchObject({
    allocation: { rule: "fixed", shares: { sales_xray: 75, company: 25 } },
  });
});
