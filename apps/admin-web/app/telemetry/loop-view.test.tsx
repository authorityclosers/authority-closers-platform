// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import {
  compareFixture,
  devicesFixture,
  fixNextFixture,
} from "../review-fixture/telemetry-loop/loop-fixture";
import {
  actionBars,
  compareQuery,
  deviceLabel,
  devicesQuery,
  fixNextQuery,
  gateWords,
  mixOf,
  modelWords,
  normalizeComparison,
  normalizeDevices,
  normalizeFixNext,
} from "./loop-data";
import { DevicesView, FixNextView, ReleasesView } from "./loop-view";

const NOW = new Date("2026-10-24T06:00:00Z");

const host = (markup: string) => {
  const element = document.createElement("div");
  element.innerHTML = markup;
  return element;
};

it("names phone models and device kinds in words, never by a person", () => {
  expect(modelWords("xiaomi", "redmi_note_8_pro")).toBe(
    "Xiaomi Redmi Note 8 Pro",
  );
  expect(modelWords("samsung", "sm-a515f")).toBe("Samsung SM-A515F");
  expect(modelWords("google", "pixel_7")).toBe("Google Pixel 7");
  expect(modelWords("", "")).toBe("Unknown phone");
  expect(
    deviceLabel({
      key: "class:web:desktop:high",
      kind: "class",
      maker: "",
      model: "",
      app: "web",
      device: "desktop",
      tier: "high",
    }),
  ).toBe("Computer, web, high-end");
  const devices = normalizeDevices(devicesFixture(NOW));
  expect(devices.available).toBe(true);
  expect(devices.totals.slowShare).toBe(0.2391);
  expect(devices.groups[0]).toMatchObject({
    label: "Xiaomi Redmi Note 8 Pro",
    people: 14,
    crashes: 2,
    speedIndex: 1.6,
  });
  expect(devices.slowest[0]).toMatchObject({
    label: "Phone, Android app, low-end",
    speedIndex: 2.9,
    appVersion: "1.0.24",
  });
  // Bars are slowest first; people add up across models.
  expect(actionBars(devices.groups, "lead_open").map((bar) => bar.p75)).toEqual(
    [3_400, 3_100, 2_480, 2_140, 1_260, 860, 620, 450, 410],
  );
  expect(mixOf(devices.groups, (group) => group.ram)[0]).toEqual({
    value: "6",
    people: 13,
  });
  // An older API's answer is a page with nothing to show, never a crash.
  expect(normalizeDevices({})).toMatchObject({ available: false, groups: [] });
});

it("draws the devices page: the answer first, sorted bars with values, the slowest tenth", () => {
  const page = host(
    renderToStaticMarkup(
      <DevicesView
        devices={normalizeDevices(devicesFixture(NOW))}
        action="lead_open"
      />,
    ),
  );
  expect(page.textContent).toContain(
    "Slowest on Phone, Android app, low-end: 3.4 s, over the 1 s limit.",
  );
  const bars = page.querySelectorAll('ol[aria-label^="Open a lead"] li');
  expect(bars).toHaveLength(9);
  // Each bar writes its value: colour never says it alone.
  expect(bars[0]?.textContent).toContain("3.4 s · 12 taps");
  expect(
    page.querySelector('section[aria-label="Slowest 10% of devices"]')
      ?.textContent,
  ).toContain("Realme RMX2185");
  expect(page.textContent).toContain("Most: 6 GB (32%)");
  expect(page.textContent).toContain("Android version");
  expect(page.textContent).not.toMatch(/person:|@/);
  const empty = host(
    renderToStaticMarkup(
      <DevicesView
        devices={normalizeDevices(devicesFixture(NOW, "empty"))}
        action="tab_switch"
      />,
    ),
  );
  expect(empty.textContent).toContain("No taps on switch tab in this window.");
  expect(empty.textContent).toContain(
    "No device has sent telemetry in this window.",
  );
});

it("compares a release with the one before and says what the gate would do", () => {
  const comparison = normalizeComparison(compareFixture(NOW));
  expect(comparison).toMatchObject({ head: "v0.87", base: "v0.86" });
  expect(gateWords(comparison)).toEqual({
    verdict: "block",
    line: "Would block promotion: open a lead got slower past the limit. The owner can override.",
  });
  const page = host(
    renderToStaticMarkup(<ReleasesView comparison={comparison} />),
  );
  const cards = [...page.querySelectorAll("article")].map(
    (card) => card.textContent,
  );
  expect(cards[0]).toContain("Release gate: hold");
  expect(cards[1]).toContain("Open a lead: slower past the limit");
  expect(cards[1]).toContain("920 ms → 1.24 s (+35%)");
  expect(cards[2]).toContain("Slow server calls: worse");
  expect(page.textContent).toContain("+3 points");
  // No regression, nothing measured: never a block.
  expect(
    gateWords({
      ...comparison,
      metrics: comparison.metrics.map((item) => ({
        ...item,
        regression: false,
        verdict: "too_few" as const,
      })),
    }).verdict,
  ).toBe("not_enough_data");
});

it("ranks what to fix next with evidence, owner and the task text, and what improved", () => {
  const fixes = normalizeFixNext(fixNextFixture(NOW));
  expect(fixes.items[0]).toMatchObject({
    key: "slow:lead_open:leads",
    owner: "Lead OS",
    score: 57,
    isNew: false,
  });
  expect(fixes.items[0]?.evidence).toContainEqual([
    "75th percentile",
    "1.24 s",
  ]);
  expect(fixes.items[0]?.evidence).toContainEqual(["slow share", "31%"]);
  const page = host(renderToStaticMarkup(<FixNextView fixNext={fixes} />));
  expect(page.querySelectorAll("ol li")).toHaveLength(6);
  expect(page.querySelectorAll("button")).toHaveLength(6);
  expect(page.textContent).toContain("suggested owner Lead OS");
  expect(page.textContent).toContain(
    "by release v0.85 880 ms, v0.86 920 ms, v0.87 1.24 s",
  );
  expect(page.textContent).toContain("Switch tab is slow on A lead");
  expect(page.textContent).toContain("Gone");
  const empty = host(
    renderToStaticMarkup(
      <FixNextView fixNext={normalizeFixNext(fixNextFixture(NOW, "empty"))} />,
    ),
  );
  expect(empty.textContent).toContain("Nothing crosses a line in this window");
});

it("builds the API addresses from the page's filters, refusing anything else", () => {
  expect(devicesQuery({ window: "24h", app: "android" })).toMatchObject({
    action: "lead_open",
    path: "/v1/admin/telemetry/devices?window=24h&app=android",
  });
  expect(
    devicesQuery({ window: "1y", app: "ios", action: "drop" }),
  ).toMatchObject({
    window: "7d",
    app: "all",
    action: "lead_open",
    path: "/v1/admin/telemetry/devices?window=7d",
  });
  expect(compareQuery({ head: "v0.87" }).path).toBe(
    "/v1/admin/telemetry/compare?head=v0.87",
  );
  expect(compareQuery({ head: "../x", base: "a b" }).path).toBe(
    "/v1/admin/telemetry/compare",
  );
  expect(fixNextQuery({ window: "30d" }).path).toBe(
    "/v1/admin/telemetry/fix-next?window=30d",
  );
});
