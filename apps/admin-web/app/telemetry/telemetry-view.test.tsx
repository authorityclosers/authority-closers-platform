// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { telemetryFixture } from "../review-fixture/telemetry/telemetry-fixture";
import {
  heatLevel,
  keepFilters,
  msWords,
  normalizeTelemetry,
  shareWords,
  slowDeviceLine,
  slowTone,
  telemetryQuery,
  vitalWords,
} from "./telemetry-data";
import { TelemetryView } from "./telemetry-view";

const NOW = new Date("2026-10-24T06:00:00Z");

const render = (raw: unknown) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <TelemetryView telemetry={normalizeTelemetry(raw)} />,
  );
  return host;
};

it("reads the API's answer and words its numbers", () => {
  const data = normalizeTelemetry(telemetryFixture(NOW));
  expect(data.available).toBe(true);
  expect(data.speed[0]).toMatchObject({
    action: "lead_open",
    slowDeviceShare: 0.4,
    devices: 52,
    slowMs: 1000,
  });
  expect(slowDeviceLine(data.speed[0])).toBe(
    "40% of devices are slow when they open a lead (their median is over 1 s).",
  );
  expect(msWords(840)).toBe("840 ms");
  expect(msWords(1840)).toBe("1.84 s");
  expect(msWords(65_000)).toBe("65 s");
  expect(msWords(null)).toBe("–");
  expect(shareWords(0.31)).toBe("31%");
  expect(shareWords(0.045)).toBe("4.5%");
  expect(slowTone(0.04)).toBe("good");
  expect(slowTone(0.18)).toBe("warn");
  expect(slowTone(0.4)).toBe("bad");
  expect(vitalWords("cls", 40)).toBe("0.04");
  expect(vitalWords("lcp", 2900)).toBe("2.9 s");
  expect(heatLevel(0, 10)).toBe(0);
  expect(heatLevel(1, 10)).toBe(1);
  expect(heatLevel(10, 10)).toBe(4);
  // An older API's answer is a page with nothing to show, never a crash.
  expect(normalizeTelemetry({})).toMatchObject({ available: false, speed: [] });
});

it("builds its address from the filters and keeps the others on each row of tabs", () => {
  const query = telemetryQuery({
    window: "30d",
    device: "phone",
    tier: "low",
    release: "v0.86.0",
    app: "nonsense",
  });
  expect(query.path).toBe(
    "/v1/admin/telemetry/overview?window=30d&release=v0.86.0&device=phone&tier=low",
  );
  expect(query.app).toBe("all");
  expect(keepFilters(query, "device")).toBe(
    "window=30d&release=v0.86.0&tier=low",
  );
  expect(telemetryQuery({ release: "v1; drop" }).release).toBeNull();
  expect(telemetryQuery({}).path).toBe(
    "/v1/admin/telemetry/overview?window=7d",
  );
});

it("shows the slow-device headline, speed by tier, vitals, the heatmap, funnels and problems", () => {
  const host = render(telemetryFixture(NOW));
  const text = host.textContent ?? "";
  // The headline is the speed panel's first line, in the tone of its share.
  const headline = host.querySelector('p[data-tone="bad"]');
  expect(headline?.textContent).toBe(
    "40% of devices are slow when they open a lead (their median is over 1 s).",
  );
  expect(text).toContain("Low-end 2.1 s · Mid-range 880 ms · High-end 460 ms");
  expect(text).toContain("11,000");
  const tones = [...host.querySelectorAll("tbody [data-tone]")].map((item) =>
    item.getAttribute("data-tone"),
  );
  expect(tones).toContain("bad");
  expect(
    host.querySelector('[aria-label="Largest paint (LCP): 2.9 s"]'),
  ).not.toBeNull();
  const heat = host.querySelector('table[aria-label="Screen views heatmap"]');
  expect(heat?.querySelectorAll("tbody tr")).toHaveLength(4);
  expect(heat?.querySelectorAll('td[data-level="4"]').length).toBeGreaterThan(
    0,
  );
  expect(text).toContain("Leads → A lead");
  expect(text).toContain("Read a section 5 s or more");
  expect(text).toContain("typeerror 3f9a21c7");
  expect(text).toContain("v1_leads_id_calls");
  expect(text).toContain("2 failed");
  expect(text).toContain("A lead, a button: 14 times by 6 people");
  expect(text).toContain("Turned off");
  // Phones get cards for the speed table.
  expect(
    host.querySelectorAll('[role="list"] [role="listitem"]').length,
  ).toBeGreaterThan(0);
});

it("says plainly when nothing was recorded yet, or the API is older", () => {
  const empty = render(telemetryFixture(NOW, "empty")).textContent ?? "";
  expect(empty).toContain("No timed taps in this window yet.");
  expect(empty).toContain("No screens viewed in this window yet.");
  const old = render({}).textContent ?? "";
  expect(old).toContain("doesn’t answer telemetry yet");
});
