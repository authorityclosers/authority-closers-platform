import { describe, expect, it } from "vitest";

import { normalizeHealth, rupees, span } from "./health-data";

describe("analysis health data", () => {
  it("defaults every missing field and joins stuck plans and runs", () => {
    const health = normalizeHealth({
      jobs: {
        by_status: { dead_letter: 2 },
        by_stage: { C5: { succeeded: 4 } },
        retried: { C2: 1, C5: 2 },
      },
      stuck: {
        plans: [
          {
            plan_id: "p1",
            recording_id: "r1",
            state: "active",
            budget_expires_at: "2026-10-10T00:00:00Z",
          },
        ],
        unfinished_runs: [
          { run_id: "u1", recording_id: null, state: "running" },
        ],
      },
      failed: [
        {
          job_id: "j1",
          stage: "C2",
          code: "provider_timeout",
          retryable: true,
        },
      ],
      cost: {
        estimated_paise: 1250,
        priced_minutes: 10,
        paise_per_minute: 125,
      },
    });
    expect(health.byStatus.dead_letter).toBe(2);
    expect(health.byStatus.succeeded).toBe(0);
    expect(health.byStage).toEqual([
      {
        stage: "C5",
        counts: {
          queued: 0,
          leased: 0,
          retry_wait: 0,
          held: 0,
          succeeded: 4,
          dead_letter: 0,
        },
      },
    ]);
    expect(health.retried).toBe(3);
    expect(health.stuck.map((item) => item.kind)).toEqual(["plan", "run"]);
    expect(health.failed[0]).toMatchObject({
      jobId: "j1",
      retryable: true,
      attempts: 0,
    });
    expect(health.cost.paisePerMinute).toBe(125);
    expect(normalizeHealth(undefined).daily).toEqual([]);
  });

  it("formats money in rupees and time in plain units", () => {
    expect(rupees(125)).toBe("₹1.25");
    expect(rupees(null)).toBe("–");
    expect(span(950)).toBe("950 ms");
    expect(span(42_000)).toBe("42 s");
    expect(span(185_000)).toBe("3 min 5 s");
    expect(span(null)).toBe("–");
  });
});
