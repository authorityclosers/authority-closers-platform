import { describe, expect, it } from "vitest";

import {
  changed,
  drafts,
  move,
  problem,
  qualityLine,
  reorder,
  sentLine,
  split,
  toQuality,
  type AdsView,
  type JourneyView,
  type ProviderView,
} from "./journey-client";
import { readSummary, stripLine } from "./journey-strip";

const stage = (
  key: string,
  label: string,
  kind: JourneyView["stages"][number]["kind"],
  extra: Partial<JourneyView["stages"][number]> = {},
) => ({
  key,
  label,
  kind,
  kindWords: kind,
  milestone: "other",
  meaning: "Something else",
  archived: false,
  origin: "template",
  leads: 0,
  ...extra,
});

const view: JourneyView = {
  version: 3,
  industry: "real_estate",
  savedAt: null,
  savedBy: null,
  canEdit: true,
  kinds: {},
  meanings: {},
  stages: [
    stage("new", "New enquiry", "new"),
    stage("not_connected", "Couldn't reach", "not_connected"),
    stage("contacted", "Contacted", "follow_up"),
    stage("site_visit_booked", "Site visit booked", "interested"),
    stage("booked", "Booked", "won"),
    stage("lost", "Lost", "lost"),
    stage("interested", "Interested", "interested", {
      archived: true,
      leads: 2,
    }),
  ],
};

describe("lead stages on the page", () => {
  it("splits the path to a sale from the stages beside it", () => {
    const { path, beside, archived } = split(drafts(view));
    expect(path.map((item) => item.key)).toEqual([
      "new",
      "contacted",
      "site_visit_booked",
      "booked",
    ]);
    expect(beside.map((item) => item.key)).toEqual(["not_connected", "lost"]);
    expect(archived.map((item) => item.key)).toEqual(["interested"]);
  });

  it("moves a stage but keeps New first", () => {
    const list = drafts(view);
    const up = move(list, "site_visit_booked", -1);
    expect(split(up).path.map((item) => item.key)).toEqual([
      "new",
      "site_visit_booked",
      "contacted",
      "booked",
    ]);
    expect(move(list, "contacted", -1)).toBe(list);
    expect(move(list, "new", 1)).toBe(list);
    expect(changed(view, up)).toBe(true);
    expect(changed(view, drafts(view))).toBe(false);
  });

  it("refuses an order that doesn't start with New", () => {
    const list = drafts(view);
    expect(
      reorder(list, ["contacted", "new", "site_visit_booked", "booked"]),
    ).toBe(list);
  });

  it("says what is wrong before saving", () => {
    const list = drafts(view);
    expect(problem(list)).toBeNull();
    expect(
      problem(
        list.map((item) =>
          item.key === "booked" ? { ...item, archived: true } : item,
        ),
      ),
    ).toMatch(/Won stage/);
    expect(
      problem(
        list.map((item) =>
          item.key === "contacted" ? { ...item, label: "Lost" } : item,
        ),
      ),
    ).toMatch(/same name/);
    expect(
      problem(
        list.map((item) =>
          item.key === "contacted" ? { ...item, label: " " } : item,
        ),
      ),
    ).toMatch(/name/);
  });
});

describe("where stages go, in words", () => {
  const provider = (extra: Partial<ProviderView> = {}): ProviderView => ({
    id: "meta",
    name: "Meta",
    brand: "meta",
    naming: "stage",
    learns: "",
    reaches: "",
    destinationWords: "dataset",
    available: true,
    configured: true,
    connected: true,
    destination: { id: "1750520232917169", name: "Fictional Homes stages" },
    on: true,
    testCode: null,
    since: null,
    matches: [],
    needsCheck: 0,
    confirmedAt: null,
    counts: { delivered: 4, pending: 1 },
    lastDeliveredAt: null,
    waitingOn: null,
    ...extra,
  });
  const ads: AdsView = {
    version: 3,
    providers: [],
    recent: [],
    settling: 0,
    sendsAt: null,
  };

  it("says where stages go and how many went", () => {
    expect(sentLine(provider(), ads)).toBe(
      "Sending to Fictional Homes stages · 4 stages sent this week · 1 waiting to send",
    );
    expect(sentLine(provider({ on: false }), ads)).toBe(
      "Switched off · Fictional Homes stages",
    );
    expect(sentLine(provider({ destination: null }), ads)).toBe(
      "No dataset chosen yet",
    );
  });

  it("sums it up in one line for Lead sources", () => {
    expect(
      stripLine({
        stages: 8,
        industry: "real_estate",
        providersOn: ["meta"],
        needsCheck: 2,
        lastDeliveredAt: null,
      }),
    ).toBe("8 stages · going to Meta · 2 new matches to check");
    expect(
      stripLine({
        stages: 6,
        industry: null,
        providersOn: [],
        needsCheck: 0,
        lastDeliveredAt: null,
      }),
    ).toBe("6 stages · not going to your ads yet");
  });

  it("ignores an answer without the fields the line needs", () => {
    expect(readSummary({})).toBeNull();
    expect(readSummary(null)).toBeNull();
    expect(readSummary({ stages: 7, providersOn: ["meta", 3] })).toEqual({
      stages: 7,
      industry: null,
      providersOn: ["meta"],
      needsCheck: 0,
      lastDeliveredAt: null,
    });
  });
});

describe("match quality", () => {
  it("shows nothing unless the answer has a real score", () => {
    expect(toQuality(null)).toBeNull();
    expect(toQuality({})).toBeNull();
    expect(toQuality({ score: "6" })).toBeNull();
    expect(toQuality({ score: Number.NaN })).toBeNull();
    expect(toQuality({ score: 3.2 })).toEqual({
      score: 3.2,
      events: 0,
      keys: {},
    });
  });

  it("reads as a plain line", () => {
    const line = qualityLine("Meta", {
      score: 6.4,
      events: 24,
      keys: { email: 100, phone: 0 },
    });
    expect(line).toContain("Meta matches 6.4 out of 10");
    expect(line).toContain("emails on every event");
    expect(line).toContain("no phone numbers yet");
  });
});
