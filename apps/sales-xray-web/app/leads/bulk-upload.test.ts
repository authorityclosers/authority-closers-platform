import { describe, expect, it } from "vitest";
import type { ImportPreview, RepView } from "./leads-client";
import type { StageView } from "./journey/journey-client";
import {
  countsFor,
  evenSplit,
  firstChoices,
  freshRows,
  sharesFor,
  startStages,
} from "./bulk-upload";

const rep = (person_id: string) => ({ person_id, name: person_id }) as RepView;
const team = [rep("asha"), rep("ravi"), rep("meera")];

describe("bulk upload's choices", () => {
  it("starts on Cold Leads, split evenly among the salespeople; sellers keep theirs", () => {
    expect(firstChoices(true)).toMatchObject({
      side: "cold",
      assign: "people",
      counts: null,
      off: [],
      step: "",
    });
    expect(firstChoices(false).assign).toBe("me");
  });

  it("counts new leads as rows less the known and the repeated", () => {
    const preview = {
      total_rows: 1000,
      importable: 990,
      known_leads: 40,
      repeats_in_file: 30,
    } as ImportPreview;
    expect(freshRows(preview)).toBe(920);
    expect(
      freshRows({ ...preview, importable: undefined, known_leads: 2000 }),
    ).toBe(0);
  });

  it("splits evenly, the first people taking the extra ones", () => {
    expect(evenSplit(10, ["a", "b", "c"])).toEqual({ a: 4, b: 3, c: 3 });
    expect(evenSplit(5, [])).toEqual({});
  });

  it("gives each salesperson on the list their count, nobody with none", () => {
    const choices = {
      ...firstChoices(true),
      assign: "people" as const,
      off: ["ravi"],
    };
    expect(countsFor(choices, team, 9)).toEqual({ asha: 5, meera: 4 });
    const typed = { ...choices, counts: { asha: 6, meera: 0 } };
    expect(sharesFor(typed, team, 9)).toEqual([
      { person_id: "asha", count: 6 },
    ]);
  });

  it("starts new leads in the first stage, Open Leads or Interested only", () => {
    const stage = (
      key: string,
      kind: string,
      milestone: string,
      archived = false,
    ) => ({ key, kind, milestone, archived }) as StageView;
    const keys = startStages([
      stage("new", "new", "lead"),
      stage("not_connected", "not_connected", "unreachable"),
      stage("open_leads", "follow_up", "contacted"),
      stage("interested", "interested", "qualified"),
      stage("meeting_scheduled", "interested", "appointment_booked"),
      stage("payment", "interested", "negotiation"),
      stage("old", "follow_up", "contacted", true),
      stage("won", "won", "won"),
    ]).map((item) => item.key);
    expect(keys).toEqual(["new", "open_leads", "interested"]);
  });
});
