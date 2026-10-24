import { describe, expect, it } from "vitest";

import type { LeadEvent } from "../leads-client";
import { shows, stagePath } from "./timeline";
import { finalLine, lastContact, moveVerb, nextStep, rotting } from "./words";

const NOW = new Date("2026-10-24T10:00:00+05:30");
const hours = (value: number) =>
  new Date(NOW.getTime() + value * 3_600_000).toISOString();

describe("a card's next step", () => {
  it("marks late, none and today", () => {
    expect(
      nextStep(
        { next_action_at: hours(-3), overdue: true, stage: "interested" },
        NOW,
      ),
    ).toEqual({ tone: "late", text: "Late 3 h" });
    expect(
      nextStep(
        { next_action_at: null, no_next_action: true, stage: "interested" },
        NOW,
      ),
    ).toEqual({ tone: "none", text: "No next step" });
    expect(
      nextStep({ next_action_at: hours(2), stage: "interested" }, NOW).tone,
    ).toBe("today");
    expect(
      nextStep({ next_action_at: hours(30), stage: "interested" }, NOW).tone,
    ).toBe("later");
    expect(nextStep({ next_action_at: null, stage: "new" }, NOW).text).toBe(
      "Call now",
    );
    expect(
      nextStep({ next_action_at: null, stage: "won", group: "won" }, NOW).tone,
    ).toBe("closed");
  });

  it("says when they were last reached", () => {
    expect(
      lastContact({ last_contact_at: hours(-2), created_at: hours(-50) }, NOW),
    ).toBe("Last contact 2 h ago");
    expect(
      lastContact({ last_contact_at: null, created_at: hours(-1) }, NOW),
    ).toBe("Came in 1 h ago");
  });

  it("shows age only past the stage's limit, never on closed leads", () => {
    expect(rotting({ stage_at: hours(-80), group: "active" }, 72, NOW)).toBe(
      true,
    );
    expect(rotting({ stage_at: hours(-10), group: "active" }, 72, NOW)).toBe(
      false,
    );
    expect(rotting({ stage_at: hours(-800), group: "lost" }, 72, NOW)).toBe(
      false,
    );
    expect(rotting({ stage_at: null, group: "active" }, 72, NOW)).toBe(false);
  });
});

describe("the sheet's button", () => {
  const move = {
    action: "move" as const,
    group: "active" as const,
    label: "Interested",
    needs: [],
  };
  it("says what happens", () => {
    expect(moveVerb(move)).toBe("Move to Interested");
    expect(moveVerb({ ...move, needs: ["meeting"] })).toBe("Book meeting");
    expect(moveVerb({ ...move, group: "lost", action: "close" })).toBe(
      "Close as Lost",
    );
    expect(moveVerb({ ...move, group: "junk", action: "close" })).toBe(
      "Mark as Junk",
    );
    expect(moveVerb({ ...move, action: "reopen" })).toBe(
      "Reopen in Interested",
    );
    expect(finalLine({ group: "junk" })).toContain("Kept apart from Lost");
    expect(finalLine({ group: "active" })).toBeNull();
  });
});

const event = (
  kind: LeadEvent["kind"],
  at: string,
  extra: Partial<LeadEvent> = {},
) => ({ kind, at, stage_label: null, ...extra }) as LeadEvent;

describe("the timeline", () => {
  // Newest first, as the lead's detail sends it.
  const events = [
    event("stage", hours(-2), {
      action: "move",
      from_label: "Interested",
      stage_label: "Meeting",
    }),
    event("note", hours(-5)),
    event("result", hours(-26), {
      action: "move",
      from_label: "New Lead",
      stage_label: "Interested",
    }),
    event("result", hours(-30)),
    event("captured", hours(-28)),
  ];

  it("walks the stages it has been in, with how long each lasted", () => {
    const path = stagePath(events, "Meeting", NOW);
    expect(path.map((step) => step.label)).toEqual([
      "New Lead",
      "Interested",
      "Meeting",
    ]);
    expect(path[1].age).toBe("1 d");
    expect(path[2]).toMatchObject({ now: true, age: "2 h" });
  });

  it("filters to stage moves, calls, meetings or notes", () => {
    expect(events.filter((item) => shows("stages", item))).toHaveLength(3);
    expect(events.filter((item) => shows("calls", item))).toHaveLength(2);
    expect(events.filter((item) => shows("notes", item))).toHaveLength(1);
    expect(shows("chats", "chat")).toBe(true);
    expect(shows("calls", "chat")).toBe(false);
  });
});

describe("waits in words", () => {
  it("reads as a time, never 1358 min", async () => {
    const { waitWords } = await import("../leads-client");
    expect(waitWords(45)).toBe("45 min");
    expect(waitWords(1358)).toBe("22 h 38 min");
    expect(waitWords(120)).toBe("2 h");
    expect(waitWords(3120)).toBe("2 d 4 h");
  });
});
