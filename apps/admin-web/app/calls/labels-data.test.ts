import { describe, expect, it } from "vitest";

import {
  latest,
  myVerdicts,
  normalizeGold,
  normalizeLabels,
  sectionLabel,
  share,
} from "./labels-data";

describe("review labels data", () => {
  const data = normalizeLabels({
    review_state: "disputed",
    effective: [
      {
        id: "1",
        kind: "verdict",
        run_id: "r1",
        section: "pillar:overview",
        value: { verdict: "wrong" },
        actor_person_id: "a",
      },
      {
        id: "2",
        kind: "verdict",
        run_id: "r2",
        section: "pillar:overview",
        value: { verdict: "correct" },
        actor_person_id: "a",
      },
      {
        id: "3",
        kind: "data_use",
        value: { use: "test" },
        actor_person_id: "a",
      },
      {
        id: "4",
        kind: "data_use",
        value: { use: "training" },
        actor_person_id: "b",
      },
      { id: "5", kind: "mystery", value: {} },
    ],
    history: [],
  });

  it("keeps known kinds, reads this run's verdicts and the latest mark", () => {
    expect(data.state).toBe("disputed");
    expect(data.effective).toHaveLength(4);
    expect(myVerdicts(data, "r1", null)).toEqual({
      "pillar:overview": "wrong",
    });
    expect(myVerdicts(data, "r1", "someone-else")).toEqual({});
    expect(latest(data, "data_use")?.value.use).toBe("training");
    expect(normalizeLabels(null).state).toBe("new");
  });

  it("labels sections and shares plainly", () => {
    expect(sectionLabel("pillar:facts")).toBe("6. Where the Deal Stands");
    expect(sectionLabel("skill:qualification")).toBe("Qualification");
    expect(share(1, 4)).toBe("25%");
    expect(share(0, 0)).toBe("–");
    const gold = normalizeGold({
      by_prompt: [
        {
          prompt_revision: "coaching-v5",
          skills_compared: 4,
          skills_agreed: 3,
        },
      ],
    });
    expect(gold.byPrompt[0]).toMatchObject({
      prompt: "coaching-v5",
      compared: 4,
      agreed: 3,
      wrong: 0,
    });
    expect(gold.note).toContain("Not an official score");
  });
});
