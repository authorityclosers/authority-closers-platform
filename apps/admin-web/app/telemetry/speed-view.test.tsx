// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { speedFixture } from "../review-fixture/telemetry-speed/speed-fixture";
import {
  endpointWords,
  frameTone,
  normalizeSpeed,
  samplesWords,
  speedQuery,
  statWords,
} from "./speed-data";
import { SpeedView } from "./speed-view";

const NOW = new Date("2026-10-27T06:00:00Z");

const render = (raw: unknown) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <SpeedView speed={normalizeSpeed(raw)} />,
  );
  return host;
};

it("asks for one window and app, and nothing else", () => {
  expect(speedQuery({})).toMatchObject({
    window: "7d",
    app: "all",
    path: "/v1/admin/telemetry/speed?window=7d",
  });
  expect(speedQuery({ window: "24h", app: "android" }).path).toBe(
    "/v1/admin/telemetry/speed?window=24h&app=android",
  );
  expect(speedQuery({ window: "1y", app: "ios" })).toMatchObject({
    window: "7d",
    app: "all",
  });
});

it("reads the answer defensively and never shows a 95th from few samples", () => {
  const speed = normalizeSpeed(speedFixture(NOW, "live"));
  expect(speed.totals.people).toBe(7);
  expect(speed.frames.byVersion[0]).toMatchObject({
    version: "1.0.38",
    sessions: 7,
    slowShare: 0.71,
  });
  expect(speed.apis.endpoints[0]?.wait.n).toBe(0);
  expect(speed.journey.steps.map((step) => step.people)).toEqual([
    7, 3, 3, 2, 2, 2,
  ]);
  // A server that sends a 95th from 3 samples is not believed.
  const odd = normalizeSpeed({
    taps: [
      {
        action: "lead_open",
        all: { n: 3, p50: 1, p75: 2, p95: 3, few: false },
      },
    ],
  });
  expect(odd.taps[0]?.all).toEqual({
    n: 3,
    p50: 1,
    p75: 2,
    p95: null,
    few: true,
  });
  // Nothing at all: empty lists, never a crash.
  const empty = normalizeSpeed(null);
  expect(empty.frames.byVersion).toEqual([]);
  expect(empty.minP95).toBe(20);
  expect(empty.journey.steps).toEqual([]);
});

it("says numbers with their sample counts", () => {
  expect(samplesWords(0, true)).toBe("no samples");
  expect(samplesWords(1, true)).toBe("1 sample, too few to tell");
  expect(samplesWords(48, false)).toBe("48 samples");
  expect(statWords({ n: 3, p50: 900, p75: 1_700, p95: null, few: true })).toBe(
    "1.7 s",
  );
  expect(statWords({ n: 0, p50: null, p75: null, p95: null, few: true })).toBe(
    "–",
  );
  expect(frameTone(0.62)).toBe("bad");
  expect(frameTone(0.08)).toBe("good");
  expect(frameTone(null)).toBe("neutral");
  expect(
    endpointWords("v1_conversation_acquisition_submissions_id_sourc"),
  ).toBe("conversation acquisition submissions · id · sourc");
  expect(endpointWords("v1_lead_desk_leads_id")).toBe("lead desk leads · id");
});

it("leads with frames, then slow calls, load, taps by tier and the journey", () => {
  const host = render(speedFixture(NOW, "live"));
  const panels = [...host.querySelectorAll("section[aria-label]")].map(
    (panel) => panel.getAttribute("aria-label"),
  );
  expect(panels).toEqual([
    "Speed in this window",
    "Frames on Android",
    "Slow API calls",
    "Load",
    "Taps by device tier",
    "The journey from Leads",
  ]);
  const text = host.textContent ?? "";
  expect(text).toContain("On 1.0.38, 71% of frames were slow and 12% froze");
  expect(text).toContain("6.3 slow calls per 100 screen views");
  expect(text).toContain("23 tests on 6 devices");
  // Sample counts sit beside the numbers; few ones are marked.
  const low = host.querySelector('td [data-few=""]');
  expect(low?.textContent).toContain("n 4");
  expect(text).toContain("Every number shows how many samples it comes from");
  // No person, workspace or call is named anywhere.
  expect(text).not.toMatch(/@|workspace [0-9a-f]{8}/i);
});

it("an empty environment says so in every panel", () => {
  const text = render(speedFixture(NOW, "empty")).textContent ?? "";
  expect(text).toContain(
    "No frame counts from the Android app in this window.",
  );
  expect(text).toContain("No slow API calls in this window.");
  expect(text).toContain("No largest-paint samples in this window.");
  expect(text).toContain("No CPU tests yet");
  expect(text).toContain("No timed taps in this window.");
  expect(text).toContain("Nobody opened Leads in this window.");
});
