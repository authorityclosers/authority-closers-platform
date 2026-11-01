import { describe, expect, it } from "vitest";
import type {
  Draft,
  Kind,
  StageView,
} from "../../leads/journey/journey-client";
import {
  stageColor,
  stageName,
  stageTone,
} from "../../leads/journey/stage-look";
import {
  MEETING_STAGES,
  addStage,
  destinations,
  live,
  meaningBlock,
  meaningOf,
  meetingOn,
  meetingStage,
  moveTo,
  readyLeft,
  recommendedMap,
  removeBlock,
  removed,
  withMeaning,
} from "./stage-editor-model";

const stage = (
  key: string,
  label: string,
  kind: Kind,
  milestone: string,
  extra: Partial<Draft> = {},
): Draft => ({
  key,
  id: key,
  label,
  kind,
  milestone,
  archived: false,
  leads: 0,
  visible: true,
  color: null,
  coldLabel: null,
  ...extra,
});

// The recommended nine (stages-views-sources.md §2).
const nine = (): Draft[] => [
  stage("new", "New Lead", "new", "lead", { coldLabel: "Unworked" }),
  stage("not_connected", "Not Connected", "not_connected", "unreachable"),
  stage("open_leads", "Open Leads", "follow_up", "contacted"),
  stage("interested", "Interested", "interested", "qualified", { leads: 4 }),
  stage(
    "meeting_scheduled",
    "Meeting Scheduled",
    "interested",
    "appointment_booked",
  ),
  stage("meeting_done", "Meeting Done", "interested", "appointment_done", {
    leads: 2,
  }),
  stage("won", "Won", "won", "won"),
  stage("lost", "Closed / Lost", "lost", "lost"),
  stage("junk", "Junk Lead", "junk", "disqualified"),
];

const keys = (list: Draft[]) =>
  live(list).map((item) => item.key ?? item.label);

describe("meanings", () => {
  it("reads each stage's meaning from its kind and milestone", () => {
    expect(nine().map(meaningOf)).toEqual([
      "untouched",
      "not_reached",
      "in_talks",
      "interested",
      "meeting",
      "meeting",
      "won",
      "lost",
      "junk",
    ]);
  });

  it("keeps the one-each meanings and a stage with leads in its kind", () => {
    const list = nine();
    const [first, notConnected, open, interested] = list;
    expect(meaningBlock(list, first, "in_talks")).toMatch(/always untouched/);
    expect(meaningBlock(list, notConnected, "in_talks")).toMatch(/Not reached/);
    expect(meaningBlock(list, open, "untouched")).toMatch(/one of these/);
    expect(meaningBlock(list, open, "won")).toBeNull();
    expect(meaningBlock(list, interested, "meeting")).toBeNull();
    expect(meaningBlock(list, interested, "won")).toMatch(/has leads/);
    expect(meaningBlock(list, open, "junk")).toMatch(/Junk stage already/);
    expect(withMeaning(open, "meeting")).toMatchObject({
      kind: "interested",
      milestone: "appointment_booked",
    });
    expect(withMeaning(interested, "interested")).toBe(interested);
  });
});

describe("the list", () => {
  it("adds a ready stage before Won and brings a removed one back with its key", () => {
    const list = addStage(nine(), {
      label: "Demo booked",
      kind: "interested",
      milestone: "appointment_booked",
    });
    expect(keys(list).slice(5, 8)).toEqual([
      "meeting_done",
      "Demo booked",
      "won",
    ]);
    expect(readyLeft(list).map((item) => item.label)).not.toContain(
      "Demo booked",
    );

    const without = removed(nine(), "open_leads");
    const back = addStage(without, {
      label: "open leads",
      kind: "follow_up",
      milestone: "contacted",
    });
    expect(back.filter((item) => item.key === "open_leads")).toHaveLength(1);
    expect(back.find((item) => item.key === "open_leads")?.archived).toBe(
      false,
    );
  });

  it("moves a stage anywhere but above the first one", () => {
    expect(keys(moveTo(nine(), "won", 2)).slice(0, 4)).toEqual([
      "new",
      "not_connected",
      "won",
      "open_leads",
    ]);
    expect(keys(moveTo(nine(), "junk", 0))[0]).toBe("new");
    const list = nine();
    expect(moveTo(list, "new", 3)).toBe(list);
    const archived = removed(nine(), "lost");
    expect(moveTo(archived, "won", 1).at(-1)?.key).toBe("lost");
  });

  it("says why a stage stays, and where a removed stage's leads may go", () => {
    const list = nine();
    expect(removeBlock(list, list[0])).toMatch(/first stage stays/);
    expect(removeBlock(list, list[1])).toMatch(/Not reached/);
    expect(removeBlock(list, list[6])).toMatch(/one Won/);
    expect(removeBlock(list, list[5])).toBeNull();
    // Open leads go to an open stage, never back to New.
    expect(destinations(list, list[5]).map((item) => item.key)).toEqual([
      "not_connected",
      "open_leads",
      "interested",
      "meeting_scheduled",
    ]);
    // Junk goes to Lost; Lost to another Lost.
    expect(destinations(list, list[8]).map((item) => item.key)).toEqual([
      "lost",
    ]);
    expect(destinations(list, list[7])).toEqual([]);
  });

  it("switches a meeting stage on and off", () => {
    const off = removed(nine(), "meeting_scheduled");
    expect(meetingStage(off, MEETING_STAGES[0])).toBeUndefined();
    const on = meetingOn(off, MEETING_STAGES[0]);
    // Back from history, before Meeting Done.
    expect(keys(on).slice(3, 6)).toEqual([
      "interested",
      "meeting_scheduled",
      "meeting_done",
    ]);
    const fresh = meetingOn(
      nine().filter((item) => item.key !== "meeting_done"),
      MEETING_STAGES[1],
    );
    const added = meetingStage(fresh, MEETING_STAGES[1]);
    expect(added?.key).toBeUndefined();
    expect(added?.milestone).toBe("appointment_done");
    expect(keys(fresh).indexOf("Meeting Done")).toBe(
      keys(fresh).indexOf("won") - 1,
    );
  });

  it("finds a meeting stage the business named its own way, by its meaning", () => {
    const own = [
      ...nine().filter((item) => !item.key?.startsWith("meeting_")),
      stage(
        "demo_completed",
        "Meeting/Demo completed",
        "interested",
        "appointment_done",
      ),
    ];
    expect(meetingStage(own, MEETING_STAGES[1])?.key).toBe("demo_completed");
    expect(meetingOn(own, MEETING_STAGES[1])).toBe(own);
    expect(meetingStage(own, MEETING_STAGES[0])).toBeUndefined();
  });
});

describe("Use recommended", () => {
  it("sends each of today's stages' leads to the stage with the same meaning", () => {
    const view = (key: string, kind: Kind, milestone: string) =>
      ({ key, kind, milestone, label: key }) as StageView;
    const before = [
      view("new", "new", "lead"),
      view("follow_up", "follow_up", "contacted"),
      view("site_visit_booked", "interested", "appointment_booked"),
      view("proposal", "interested", "proposal"),
    ];
    const after = nine().map((item) => ({ ...item }) as unknown as StageView);
    const open = [
      "new",
      "not_connected",
      "open_leads",
      "interested",
      "meeting_scheduled",
      "meeting_done",
    ];
    const map = recommendedMap(before, {
      template: "recommended",
      stages: after,
      landings: [
        {
          fromKey: "new",
          fromLabel: "",
          toKey: "new",
          toLabel: "",
          leads: 2,
          choices: open,
        },
        {
          fromKey: "follow_up",
          fromLabel: "",
          toKey: "open_leads",
          toLabel: "",
          leads: 3,
          choices: open,
        },
        {
          fromKey: "site_visit_booked",
          fromLabel: "",
          toKey: "interested",
          toLabel: "",
          leads: 1,
          choices: open,
        },
        {
          fromKey: "proposal",
          fromLabel: "",
          toKey: "new",
          toLabel: "",
          leads: 1,
          choices: open,
        },
        {
          fromKey: "empty",
          fromLabel: "",
          toKey: "new",
          toLabel: "",
          leads: 0,
          choices: open,
        },
      ],
    });
    expect(map).toEqual({
      new: "new",
      follow_up: "open_leads",
      site_visit_booked: "meeting_scheduled",
      // Never back into the first stage.
      proposal: "interested",
    });
  });
});

describe("how a stage looks", () => {
  it("takes its own dot, else its meaning's colour, and its Cold name on Cold", () => {
    const [first, , open, , meeting] = nine();
    expect(stageColor(open)).toBe("teal");
    expect(stageColor(meeting)).toBe("violet");
    expect(stageColor({ ...open, color: "pink" })).toBe("pink");
    expect(stageTone(open)).toBe("var(--lx-teal)");
    expect(stageName(first, "cold")).toBe("Unworked");
    expect(stageName(first, "inbound")).toBe("New Lead");
    expect(stageName(open, "cold")).toBe("Open Leads");
    // A list that never named its Cold first stage reads Unworked (ph1-48).
    expect(
      stageName({ kind: "new", label: "New lead", coldLabel: null }, "cold"),
    ).toBe("Unworked");
    expect(
      stageName({ kind: "new", label: "Fresh", coldLabel: null }, "cold"),
    ).toBe("Fresh");
  });
});
