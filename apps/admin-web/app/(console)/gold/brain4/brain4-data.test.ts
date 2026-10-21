import { describe, expect, it } from "vitest";

import {
  decimal,
  lean,
  normalizeBrain4,
  percent,
  withInterval,
} from "./brain4-data";

describe("Brain 4.0 evaluation data", () => {
  it("keeps the server's figures and defaults whatever is missing", () => {
    const data = normalizeBrain4({
      version: "brain4-eval/1",
      gold: { lines: 90, calls: 30, calls_with_brain4: 12 },
      classic_acceptance: {
        agree: 60,
        partly: 0,
        disagree: 30,
        agree_rate: 0.6667,
      },
      dimensions: [
        {
          id: "D18",
          label: "Setting Clear Next Steps",
          category: "moving_the_sale_forward",
          pointers: ["next_steps"],
          brain4: {
            calls: 30,
            lines: 30,
            exact: 1,
            exact_ci: [0.9, 1],
            kappa: null,
          },
          classic: { calls: 30, lines: 30, exact: 0 },
          readiness: { state: "beta", needs: ["50 gold calls (has 30)"] },
        },
        { id: "D01", brain4: "broken" },
      ],
      alerts: [
        { scorer: "classic", dimension: null, before: 0.7, recent: 0.5 },
      ],
    });
    expect(data.gold).toMatchObject({ calls: 30, calls_with_brain4: 12 });
    expect(data.classic_acceptance.agree_rate).toBe(0.6667);
    expect(data.classic_acceptance.reasons).toEqual({});
    expect(data.dimensions[0].brain4.exact_ci).toEqual([0.9, 1]);
    expect(data.dimensions[0].readiness.state).toBe("beta");
    expect(data.dimensions[1].brain4.lines).toBe(0);
    expect(data.dimensions[1].readiness.state).toBe("needs_data");
    expect(data.alerts).toHaveLength(1);
    expect(normalizeBrain4(null).dimensions).toEqual([]);
  });

  it("formats rates, intervals and lean in words", () => {
    expect(percent(0.6249)).toBe("62%");
    expect(percent(null)).toBe("—");
    expect(withInterval(0.62, [0.48, 0.74])).toBe("62% (48%–74%)");
    expect(withInterval(null, [0.1, 0.2])).toBe("—");
    expect(withInterval(0.71, [0.55, 0.84], (n) => decimal(n))).toBe(
      "0.71 (0.55–0.84)",
    );
    expect(lean(0.4)).toBe("+0.40 (more generous)");
    expect(lean(-0.25)).toBe("−0.25 (stricter)");
    expect(lean(0)).toBe("0.00");
  });
});
