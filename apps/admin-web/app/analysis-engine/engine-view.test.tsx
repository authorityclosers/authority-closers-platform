// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { engineFixture } from "../review-fixture/engine/engine-fixture";
import {
  engineQuery,
  normalizeEngine,
  ratioTone,
  ratioWords,
  tokenWords,
} from "./engine-data";
import { EngineView } from "./engine-view";

const NOW = new Date("2026-10-22T10:00:00Z");

const render = (raw: unknown) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <EngineView engine={normalizeEngine(raw)} />,
  );
  return host;
};

it("reads the engine: registry, modules, and plans with this window's and the measured mix's rates", () => {
  const engine = normalizeEngine(engineFixture(NOW));
  expect(engine.registry.version).toBe("analysis-engine-registry/0");
  expect(engine.registry.digest).toMatch(/^[0-9a-f]{10}$/);
  expect(engine.window).toMatchObject({ calls: 31, analysed: 18, short: 13 });
  const transcript = engine.modules.find((row) => row.id === "c2.flash-lite");
  expect(transcript).toMatchObject({ ratio: 1.288, drifting: true });
  const luna = engine.modules.find((row) => !row.modelled);
  expect(luna).toMatchObject({
    stage: "C4",
    model: "gpt-6-luna:flex",
    expectedRupees: null,
    unpricedSteps: 2,
  });
  const today = engine.plans.find((plan) => plan.id === "today");
  expect(today?.window?.perMinute).toBe(0.752);
  // The registry's own projection: ₹0.709/min plus fast lead facts on short calls.
  expect(today?.reference?.perMinute).toBeCloseTo(0.714, 3);
  expect(today?.referenceWithUptake).toBeNull();
  const onDemand = engine.plans.find(
    (plan) => plan.id === "v2-report-on-demand",
  );
  expect(onDemand?.onDemand).toEqual(["c5.after-one-pass"]);
  expect(onDemand?.referenceWithUptake?.perMinute).toBeGreaterThan(
    onDemand?.reference?.perMinute ?? 1,
  );
  expect(ratioTone(1.1, 0.25)).toBe("good");
  expect(ratioTone(1.4, 0.25)).toBe("warn");
  expect(ratioTone(3.2, 0.25)).toBe("bad");
  expect(ratioTone(null, 0.25)).toBe("neutral");
  expect(ratioWords(1.288)).toBe("×1.29");
  expect(ratioWords(null)).toBe("–");
  expect(tokenWords(860)).toBe("860");
  expect(tokenWords(118_400)).toBe("118.4k");
  expect(tokenWords(null)).toBe("–");
  // An old server's empty answer is a page with nothing to show, never a crash.
  expect(normalizeEngine({})).toMatchObject({
    available: false,
    modules: [],
    plans: [],
  });
});

it("bounds the page's query to what the API takes", () => {
  expect(engineQuery().path).toBe(
    "/v1/admin/conversation/engine?env=production&days=7",
  );
  expect(engineQuery("development", "30").path).toBe(
    "/v1/admin/conversation/engine?env=development&days=30",
  );
  expect(engineQuery("all", "90")).toMatchObject({
    environment: "production",
    days: "7",
  });
});

it("shows expected against actual, the drifting module, the module with no fit, plans and the registry", () => {
  const text = render(engineFixture(NOW)).textContent ?? "";
  expect(text).toContain("Expected against actual · production");
  expect(text).toContain("Modules off their fit");
  expect(text).toContain("×1.29");
  expect(text).toContain("no fit in the registry");
  expect(text).toContain("2 unpriced steps");
  expect(text).toContain(
    "Today: one pass v1 and the full report, Gemini standard",
  );
  expect(text).toContain("if 10% ask for the full report");
  expect(text).toContain("Registry · v0");
  expect(text).toContain("16 real calls' receipts");
});

it("still shows the plans and the registry when an environment has no export", () => {
  const host = render(engineFixture(NOW, "empty"));
  const text = host.textContent ?? "";
  expect(text).toContain("isn’t in the metrics store yet");
  expect(text).not.toContain("Modules off their fit");
  expect(text).toContain("Plans");
  expect(text).toContain("Registry · v0");
});

it("warns when the export is old", () => {
  expect(render(engineFixture(NOW, "stale")).textContent).toContain(
    "the collector may have stopped",
  );
});
