import { expect, it } from "vitest";

import { recentSteps, TelemetryClient } from "../telemetry";

// Demo P0 (26 Oct 2026): a bug report carries the last app steps; fifty
// since the advanced reporter (31 Oct 2026).
it("keeps the last fifty steps, names, times and routes", () => {
  let tick = 0;
  const client = new TelemetryClient(
    {
      fetch: async () => new Response(null, { status: 204 }),
      now: () => new Date(Date.UTC(2026, 9, 26, 4, 30, tick++)),
      id: () => `id-${tick}`,
      context: () => ({ route: "/leads", device: "phone", app: "android" }),
    },
    true,
  );
  for (let n = 0; n < 55; n++)
    client.track("bug_report_opened" as never, {} as never);
  const steps = recentSteps();
  expect(steps).toHaveLength(50);
  expect(steps.at(-1)).toEqual({
    event: "bug_report_opened",
    at: "2026-10-26T04:30:54.000Z",
    route: "/leads",
  });
});

it("keeps a step's words from fixed lists, never ids or text", () => {
  const client = new TelemetryClient(
    {
      fetch: async () => new Response(null, { status: 204 }),
      now: () => new Date(Date.UTC(2026, 9, 31, 4, 30, 0)),
      id: () => "id",
      context: () => ({ route: "/leads", device: "phone", app: "android" }),
    },
    true,
  );
  client.track("sx.lead_stage_moved", {
    via: "sheet",
    from_kind: "new",
    to_kind: "interested",
  });
  client.track("sx.tap", { target: "button", zone: "r2c1", screen: "leads" });
  // A measurement is not a step.
  client.track("sx.scroll_depth", { depth: 50, screen: "leads" });
  const [moved, tapped] = recentSteps().slice(-2);
  expect(moved?.detail).toEqual({
    via: "sheet",
    from_kind: "new",
    to_kind: "interested",
  });
  // The tap's place on the screen is not a word the trail keeps.
  expect(tapped?.detail).toEqual({ target: "button", screen: "leads" });
});
