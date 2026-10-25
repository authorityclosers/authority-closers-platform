// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import {
  sellerFixture,
  type SellerFixtureState,
} from "../review-fixture/seller/seller-fixture";
import { normalizeTimeline } from "./seller-data";
import { SellerTimeline } from "./seller-timeline";

const render = (state: SellerFixtureState) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <SellerTimeline timeline={normalizeTimeline(sellerFixture(state))} />,
  );
  return host;
};

it("leads with the newest gap, then each day's server and phone lines and times", () => {
  const host = render("gap");
  const summary = host.querySelector('[aria-label="Summary"]')!;
  expect(summary.getAttribute("data-tone")).toBe("bad");
  expect(summary.textContent).toContain("Needs a look");
  expect(summary.textContent).toContain(
    "23 Oct: 14 calls, 0 results saved — the phone saved 9 results that never reached the server",
  );
  const days = [...host.querySelectorAll("h3")].map((node) => node.textContent);
  expect(days).toEqual(["23 Oct", "22 Oct"]);
  const gaps = host.querySelector('[aria-label="Gaps on 23 Oct"]')!;
  expect(gaps.querySelector('[data-tone="bad"]')?.textContent).toBe(
    "9 results saved on the phone, 0 reached the server",
  );
  const times = host.querySelector('[aria-label="Times on 23 Oct"]')!;
  expect(times.textContent).toContain(
    "09:11Signed in, opened Fictional Realty",
  );
  expect(times.textContent).toContain(
    "10:32New install e5f6a7b8 logged its first call",
  );
  expect(host.textContent).toContain("Android app · phone");
  expect(host.textContent).toContain(
    "Fictional phone 8 · Android 13 · Play · version 1.0.26",
  );
  expect(host.textContent).toContain("Also seen: 1.0.25");
  expect(host.textContent).toContain("Usage analytics on");
  expect(host.textContent).toContain(
    "Setup report, install e5f6a7b8 · Fictional Realty",
  );
  expect(host.textContent).toContain("Organisation · Member");
  expect(host.textContent).toContain("Terms 2026-10-01, accepted");
});

it("says so when there are no gaps, and when nothing happened", () => {
  const clean = render("clean");
  expect(
    clean.querySelector('[aria-label="Summary"]')?.getAttribute("data-tone"),
  ).toBe("good");
  expect(clean.textContent).toContain("No gaps in the last 14 days");
  expect(clean.textContent).toContain("Download link");
  const empty = render("empty");
  expect(empty.textContent).toContain("No activity in the last 14 days");
  expect(empty.textContent).toContain("Nothing in this window");
  expect(empty.textContent).toContain("No usage data in this window");
  expect(empty.textContent).toContain("The phone app hasn't reported here.");
  // Never prices, never what a call or note said: counts, times and states only.
  expect(render("gap").textContent).not.toMatch(/₹|price|transcript/i);
});
