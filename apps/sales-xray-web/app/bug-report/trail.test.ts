import { expect, it } from "vitest";

import { recentSteps, TelemetryClient } from "../telemetry";

// Demo P0 (26 Oct 2026): a bug report carries the last twenty app steps.
it("keeps the last twenty steps, names, times and routes only", () => {
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
  for (let n = 0; n < 25; n++)
    client.track("bug_report_opened" as never, {} as never);
  const steps = recentSteps();
  expect(steps).toHaveLength(20);
  expect(steps.at(-1)).toEqual({
    event: "bug_report_opened",
    at: "2026-10-26T04:30:24.000Z",
    route: "/leads",
  });
});
