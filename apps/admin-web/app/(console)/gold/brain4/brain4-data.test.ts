import { describe, expect, it } from "vitest";

import {
  decimal,
  lean,
  normalizeBrain4,
  percent,
  ratio,
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

  it("reads a checkpoint and keeps a broken one out", () => {
    const data = normalizeBrain4({
      checkpoints: [
        {
          checkpoint: "gold-v1/2026-10-21",
          title: "Gold v1",
          calls: 6,
          labels: { positive: 27, negative: 9, mixed: 7, total: 43 },
          scorers: [
            {
              scorer: "classic",
              overall: {
                labels: 43,
                rated: 42,
                agree: 27,
                agreement: 0.643,
                wilson: [0.49, 0.77],
              },
              by_label: { negative: { labels: 9, rated: 9, agree: 2 } },
              dimensions: { D05: { labels: 6, rated: 6, agree: 3 } },
            },
          ],
        },
      ],
    });
    const point = data.checkpoints[0];
    expect(point.scorers[0].overall.agree).toBe(27);
    expect(ratio(point.scorers[0].by_label.negative)).toBe("2/9");
    expect(ratio({ agree: 0, rated: 0 })).toBe("—");
    expect(normalizeBrain4({ checkpoints: "x" }).checkpoints).toEqual([]);
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

describe("Blind ratings and the checkpoint sample", () => {
  it("reads blind figures and defaults a missing or broken section", () => {
    const data = normalizeBrain4({
      blind: {
        ratings: 36,
        calls: 2,
        calls_with_brain4: 2,
        reviewers: 1,
        dimensions: [
          {
            id: "D16",
            label: "Handling Objections",
            ratings: 2,
            brain4: { calls: 2, rated: 2, exact: 0.5, lean: 1 },
            readiness: { state: "needs_data", needs: ["at least 20"] },
          },
          {
            id: "D03",
            brain4: "broken",
            readiness: { state: "undecidable", needs: ["audio"] },
            undecidable: "audio",
          },
        ],
        between_raters: { pairs: 0 },
        moments: { moments: 3, criticisms: 2, marked: 1, caught_rate: 0.5 },
      },
      sample: {
        name: "fresh-1",
        mode: "brain4_blind",
        total: 25,
        chosen: 4,
        minutes: [10, 30],
        at_least: { price: { want: 15, have: 3 } },
      },
    });
    expect(data.blind.ratings).toBe(36);
    expect(data.blind.dimensions[0].brain4.exact).toBe(0.5);
    expect(data.blind.dimensions[1].brain4.rated).toBe(0);
    expect(data.blind.dimensions[1].undecidable).toBe("audio");
    expect(data.blind.between_raters.gate0).toBe(false);
    expect(data.blind.moments.caught_rate).toBe(0.5);
    expect(data.sample?.at_least.price).toEqual({ want: 15, have: 3 });
    expect(data.sample?.minutes).toEqual([10, 30]);
    const old = normalizeBrain4({ blind: "broken" });
    expect(old.blind.ratings).toBe(0);
    expect(old.blind.dimensions).toEqual([]);
    expect(old.sample).toBeNull();
  });
});
