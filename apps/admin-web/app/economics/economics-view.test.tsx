// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { economicsFixture } from "../review-fixture/economics/economics-fixture";
import {
  economicsQuery,
  marginTone,
  normalizeEconomics,
  rate,
  rupees,
  share,
} from "./economics-data";
import { EconomicsView } from "./economics-view";

const render = (raw: unknown) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <EconomicsView economics={normalizeEconomics(raw)} />,
  );
  return host.textContent ?? "";
};

it("reads offers, routes, break-even, fixed costs and the trial", () => {
  const economics = normalizeEconomics(economicsFixture());
  expect(economics.offers.map((offer) => offer.id)).toEqual([
    "personal.monthly.web",
    "personal.monthly.play",
    "personal.yearly.web",
    "personal.yearly.play",
    "organisation.monthly.web",
    "organisation.yearly.web",
  ]);
  const personal = economics.offers[0];
  expect(personal?.net).toBeCloseTo(2058.82, 2);
  expect(
    personal?.margins["today-brain4-read"]?.map((item) => item.use),
  ).toEqual([0.25, 0.5, 1]);
  expect(personal?.breakEven["1.0"]?.total).toBeGreaterThan(30);
  expect(economics.routes[0]).toMatchObject({
    id: "measured",
    source: "measured",
  });
  expect(economics.breakEvenRoute).toBe("today-brain4-read");
  expect(economics.fixed.items[0]).toMatchObject({
    key: "ai_test_calls",
    source: "measured",
  });
  expect(economics.measured.uncharged?.calls).toBe(4);
  expect(economics.trial.minutes).toBe(60);
  expect(normalizeEconomics({})).toMatchObject({ offers: [], routes: [] });
});

it("words money, rates and shares, and tones margins against the target", () => {
  expect(rupees(1376.4)).toBe("₹1,376");
  expect(rate(0.853)).toBe("₹0.85");
  expect(share(0.6686)).toBe("67%");
  expect(rupees(null)).toBe("–");
  expect(marginTone(0.67, 0.5)).toBe("good");
  expect(marginTone(0.4, 0.5)).toBe("warn");
  expect(marginTone(-0.1, 0.5)).toBe("bad");
  expect(marginTone(null, 0.5)).toBe("neutral");
  expect(economicsQuery().path).toBe(
    "/v1/admin/economics?env=production&days=30",
  );
  expect(economicsQuery("staging", "7").path).toBe(
    "/v1/admin/economics?env=staging&days=7",
  );
  expect(economicsQuery("all", "90")).toMatchObject({
    environment: "production",
    days: "30",
  });
});

it("shows margins per plan, routes, break-even, fixed costs, top-ups and the trial", () => {
  const text = render(economicsFixture());
  expect(text).toContain("Margin a month per plan");
  expect(text).toContain("Personal, monthly, web");
  expect(text).toContain("Organisation, monthly, web");
  expect(text).toContain("Cost per minute by analysis route");
  expect(text).toContain("Break-even at full use");
  expect(text).toContain("AI on calls never charged");
  expect(text).toContain("Claude Max 20x for the agents");
  expect(text).toContain("estimate");
  expect(text).toContain("Free trial · 60 min");
});

it("names a plan that loses money", () => {
  const raw = economicsFixture();
  const text = render({
    ...raw,
    warnings: [
      {
        offer: "personal.monthly.play",
        route: "today-brain4-read",
        kind: "loss_at_full_use",
      },
    ],
  });
  expect(text).toContain(
    "Personal, monthly, Play Store on Today loses money at full use.",
  );
});
