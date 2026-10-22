// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { meterFixture } from "../review-fixture/meter/meter-fixture";
import { CostMeter } from "./cost-meter";
import {
  ageWords,
  isStale,
  meterTone,
  normalizeMeter,
  perMinuteWords,
  scaleOf,
} from "./meter-data";

const NOW = new Date("2026-10-22T10:00:00Z");

const render = (raw: unknown, detail = false) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <CostMeter meter={normalizeMeter(raw)} detail={detail} />,
  );
  return host;
};

it("reads the meter, words the rate and ages, and colours against the targets", () => {
  const meter = normalizeMeter(meterFixture(NOW));
  expect(meter.windows.map((slot) => slot.key)).toEqual(["today", "24h", "7d"]);
  expect(meter.windows[2]?.allIn).toEqual({
    calls: 69,
    audioMinutes: 318.2,
    rupees: 339.8,
    perMinute: 1.068,
  });
  expect(meter.fx.mode).toBe("daily");
  expect(meter.targets).toEqual([0.4, 0.1]);
  expect(perMinuteWords(1.066)).toBe("₹1.07/min");
  expect(perMinuteWords(null)).toBe("–");
  expect(meterTone(0.08, [0.4, 0.1])).toBe("good");
  expect(meterTone(0.3, [0.4, 0.1])).toBe("warn");
  expect(meterTone(1.07, [0.4, 0.1])).toBe("bad");
  expect(meterTone(null, [0.4, 0.1])).toBe("neutral");
  expect(ageWords(40)).toBe("updated just now");
  expect(ageWords(180)).toBe("updated 3 min ago");
  expect(ageWords(3 * 3600)).toBe("updated 3 h ago");
  expect(ageWords(null)).toBe("no export yet");
  expect(isStale(180)).toBe(false);
  expect(isStale(3 * 3600)).toBe(true);
  const scale = scaleOf(1.066, [0.4, 0.1]);
  expect(scale.value).toBeCloseTo(100 / 1.1, 1);
  expect(scale.targets.map((mark) => Math.round(mark.at))).toEqual([34, 9]);
  // An old server's empty answer is a meter with nothing to show, never a crash.
  expect(normalizeMeter({})).toMatchObject({ available: false, windows: [] });
});

it("shows Home's three numbers with their tone, freshness, rate and a way to the detail", () => {
  const host = render(meterFixture(NOW));
  const text = host.textContent ?? "";
  expect(text).toContain("₹/min now · production");
  expect(text).toContain("updated 3 min ago");
  expect(text).toContain("Rupees at each day's ECB rate (latest ₹94.93 per $1");
  // The panel is a labelled section too; the three windows sit inside it.
  const tiles = [...host.querySelectorAll("section section[aria-label]")].map(
    (tile) => tile.getAttribute("aria-label"),
  );
  expect(tiles).toEqual([
    "Today: ₹0.09/min",
    "Last 24 hours: ₹0.34/min",
    "Last 7 days: ₹1.07/min",
  ]);
  const tones = [...host.querySelectorAll("strong[data-tone]")].map((value) =>
    value.getAttribute("data-tone"),
  );
  expect(tones).toEqual(["good", "warn", "bad"]);
  expect(text).toContain("₹0.40");
  expect(text).toContain("₹0.10");
  expect(host.querySelector('a[href="/health#cost-meter"]')).not.toBeNull();
  expect(host.querySelector("dl")).toBeNull();
});

it("shows Health's split and versions, and says when the numbers are old", () => {
  const host = render(meterFixture(NOW, "stale"), true);
  const text = host.textContent ?? "";
  expect(text).toContain("Full reports₹1.14/min 63 calls · 286.6 min");
  expect(text).toContain("Short or data-only₹0.44/min 6 calls · 31.5 min");
  expect(text).toContain("46 calls · 191.1 min · no cost");
  expect(text).toContain("from 3 h ago: the collector may");
  // Phones get one card per version (the same rows).
  expect(host.querySelectorAll('[role="list"] [role="listitem"]')).toHaveLength(
    2,
  );
  const rows = [...host.querySelectorAll("tbody tr")].map(
    (row) => row.querySelector("code")?.textContent,
  );
  expect(rows[0]).toContain("one-pass-v1");
  expect(rows).toHaveLength(2);
});

it("says plainly when the export is missing or nothing ran yet", () => {
  const missing =
    render({ environment: "production", available: false }).textContent ?? "";
  expect(missing).toContain("isn’t in the metrics store yet");
  const empty = render(meterFixture(NOW, "empty")).textContent ?? "";
  expect(empty).toContain("No analysed calls yet");
});
