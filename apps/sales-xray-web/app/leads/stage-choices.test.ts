import { expect, it } from "vitest";

import { stageChoices } from "./lead-sheet";

it("offers the business's own stages after a call, with the desk's kind for each", () => {
  const choices = stageChoices({
    stage_choices: [
      {
        key: "contacted",
        label: "Contacted",
        kind: "follow_up",
        meaning: "You spoke to them",
      },
      {
        key: "site_visit_booked",
        label: "Site visit booked",
        kind: "interested",
        meaning: "A meeting or visit is booked",
      },
      { key: "booked", label: "Booked", kind: "won", meaning: "They bought" },
      { key: "lost", label: "Lost", kind: "lost", meaning: "They won't buy" },
    ],
  });
  expect(
    choices.map((item) => [item.label, item.key, item.step, item.tone]),
  ).toEqual([
    ["Contacted", "follow_up", "contacted", "later"],
    ["Site visit booked", "interested", "site_visit_booked", "warm"],
    ["Booked", "won", "booked", "good"],
    ["Lost", "lost", "lost", "bad"],
  ]);
});

it("keeps the desk's four choices when the business has no stage list", () => {
  const choices = stageChoices({});
  expect(choices.map((item) => item.key)).toEqual([
    "interested",
    "follow_up",
    "won",
    "lost",
  ]);
  expect(choices.every((item) => item.step === undefined)).toBe(true);
});
